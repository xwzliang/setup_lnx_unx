#!/usr/bin/env python3
"""Export the enabled OMV Samba shares backed by the physical disk on sata1."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory

if __package__:
    from . import install as omv
    from .configure_guest import (
        FILESYSTEM_UUID, FOLDER, LIST_DATA_DEVICES, MOUNT, POOL, SHARE, existing_data_device, existing_share_layout,
    )
else:
    import install as omv
    from configure_guest import (
        FILESYSTEM_UUID, FOLDER, LIST_DATA_DEVICES, MOUNT, POOL, SHARE, existing_data_device, existing_share_layout,
    )

MERGERFS_TYPES = {"mergerfs", "fuse.mergerfs"}


def read_model(host, model):
    rows = json.loads(omv.remote(host, "sudo", "-n", "omv-confdbadm", "read", model).stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise omv.InstallError(f"OMV did not return a list of {model} records.")
    return rows


def source_filesystem(args):
    if args.filesystem_uuid is not None:
        return args.filesystem_uuid
    config = omv.remote(args.proxmox, "qm", "config", str(args.vmid), "--current").stdout
    identity = omv.sata1_disk_identity(args.proxmox, config)
    if "uuid" in identity:
        return identity["uuid"]
    devices = json.loads(omv.remote(args.omv, *LIST_DATA_DEVICES).stdout)["blockdevices"]
    return existing_data_device(identity, devices)["uuid"]


def data_mount(host, mounts, filesystem_uuid):
    sources = {filesystem_uuid, f"UUID={filesystem_uuid}", f"/dev/disk/by-uuid/{filesystem_uuid}"}
    ext4 = [mount for mount in mounts if mount["type"] == "ext4"]
    candidates = [mount for mount in ext4 if mount["fsname"] in sources]
    if not candidates:
        # Older OMV configurations can reference the same disk by a label or device name.
        active = json.loads(omv.remote(host, "sudo", "-n", "findmnt", "--json", "--list",
                                       "--output", "TARGET,UUID,FSTYPE").stdout)
        directories = {entry["target"] for entry in active["filesystems"]
                       if entry["fstype"] == "ext4" and entry["uuid"] == filesystem_uuid}
        candidates = [mount for mount in ext4 if mount["dir"] in directories]
    if len(candidates) != 1:
        raise omv.InstallError("Expected exactly one OMV mount for the ext4 filesystem on sata1.")
    return candidates[0]


def mergerfs_branch(mount_id, pools, root):
    matches = [pool for pool in pools if pool["mntentref"] == mount_id]
    if len(matches) != 1:
        raise omv.InstallError("Expected one mergerfs pool record for the Samba share.")
    branches = []
    for entry in matches[0]["paths"].split(":"):
        directory, separator, mode = entry.strip().rpartition("=")
        if not separator or mode not in {"RW", "RO", "NC"}:
            directory, mode = entry.strip(), "RW"
        path = PurePosixPath(directory)
        if not path.is_absolute() or ".." in path.parts or any(char in directory for char in "*?[]\\"):
            raise omv.InstallError("The Samba share uses a mergerfs branch that cannot be mapped to a single disk.")
        branches.append((path, mode))
    selected = [(path, mode) for path, mode in branches if path.is_relative_to(root)]
    if not selected:
        return None
    if len(branches) != 1 or selected[0][1] == "NC":
        raise omv.InstallError("The Samba share spans mergerfs branches or uses a no-create branch on sata1.")
    return selected[0]


def share_path(folder, mount, data, pools, mounts):
    root = PurePosixPath(data["dir"])
    if not root.is_absolute() or root == PurePosixPath("/") or ".." in root.parts:
        raise omv.InstallError("The OMV data mount directory is invalid.")

    branch = (root, "RW") if mount["uuid"] == data["uuid"] else None
    if mount["type"] in MERGERFS_TYPES:
        branch = mergerfs_branch(mount["uuid"], pools, root)
    if branch is None:
        return None

    relative = folder["reldirpath"]
    if not isinstance(relative, str) or not relative:
        raise omv.InstallError(f"The shared folder {folder['name']!r} has no saved directory.")
    path = PurePosixPath(relative.lstrip("/"))
    if ".." in path.parts:
        raise omv.InstallError(f"The shared folder {folder['name']!r} has an invalid directory.")
    directory, mode = branch
    resolved = directory / path
    if any(other.is_relative_to(root) and (resolved.is_relative_to(other) or other.is_relative_to(resolved))
           for other in (PurePosixPath(entry["dir"]) for entry in mounts if entry["uuid"] != data["uuid"])):
        raise omv.InstallError(f"The shared folder {folder['name']!r} crosses another mount on sata1.")
    return resolved.relative_to(root).as_posix(), mode == "RO"


def index_records(rows, model):
    records = {entry["uuid"]: entry for entry in rows}
    if len(records) != len(rows):
        raise omv.InstallError(f"OMV returned duplicate {model} identifiers.")
    return records


def export_shares(host, filesystem_uuid):
    shares = [share for share in read_model(host, SHARE) if share["enable"]]
    folders = index_records(read_model(host, FOLDER), FOLDER)
    mounts = index_records(read_model(host, MOUNT), MOUNT)
    data = data_mount(host, mounts.values(), filesystem_uuid)
    exports = [(share, folders[share["sharedfolderref"]]) for share in shares]
    pools = (read_model(host, POOL) if any(
        mounts[folder["mntentref"]]["type"] in MERGERFS_TYPES for _, folder in exports
    ) else [])
    layout, skipped = [], []
    for share, folder in exports:
        name = folder["name"]
        result = share_path(folder, mounts[folder["mntentref"]], data, pools, mounts.values())
        if result is None:
            skipped.append(name)
            continue
        path, readonly_branch = result
        layout.append({"name": name, "path": path,
                       "readonly": share["readonly"] or readonly_branch, "browseable": share["browseable"]})
    if not layout:
        raise omv.InstallError("No enabled Samba shares resolve to the filesystem on sata1.")
    return existing_share_layout(sorted(layout, key=lambda share: share["name"].casefold())), skipped


def save_profile(path, shares):
    if path.is_symlink() or not path.is_file():
        raise omv.InstallError("Use an existing regular Proxmox profile file.")
    original = path.read_text()
    profile = json.loads(original)
    vm_setup = profile.get("vm_setup") if isinstance(profile, dict) else None
    if not isinstance(vm_setup, dict):
        raise omv.InstallError("The Proxmox profile needs an enabled vm_setup object.")
    if "profiles" in vm_setup:
        profiles = vm_setup["profiles"]
        if not isinstance(profiles, list) or "omv" not in profiles:
            raise omv.InstallError("The Proxmox profile must include the omv VM.")
    if vm_setup.get("omv_shares") == shares:
        return
    vm_setup["omv_shares"] = shares
    with TemporaryDirectory(prefix=".omv-shares-", dir=path.parent) as temporary:
        pending = Path(temporary) / path.name
        pending.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
        pending.chmod(stat.S_IMODE(path.stat().st_mode))
        if path.is_symlink() or path.read_text() != original:
            raise omv.InstallError("The Proxmox profile changed during export. Retry after the edit is complete.")
        pending.replace(path)


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omv", default="omv", help="SSH target for the source OMV (default omv)")
    parser.add_argument("--proxmox", default="pve", help="SSH target for the source Proxmox host (default pve)")
    parser.add_argument("--vmid", type=omv.between(100, 999999999), default=102, help="source OMV VM ID (default 102)")
    parser.add_argument("--filesystem-uuid", type=str.lower,
                        help="use this ext4 filesystem UUID and skip the Proxmox lookup")
    parser.add_argument("--profile", type=Path, help="update this local Proxmox profile instead of printing a fragment")
    args = parser.parse_args()
    for alias in (args.omv, args.proxmox):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*(?:@[a-zA-Z0-9][a-zA-Z0-9._-]*)?", alias):
            parser.error("Invalid SSH target.")
    if args.filesystem_uuid is not None and not re.fullmatch(FILESYSTEM_UUID, args.filesystem_uuid):
        parser.error("Use the ext4 filesystem UUID for --filesystem-uuid.")
    return args


def main():
    args = arguments()
    try:
        layout, skipped = export_shares(args.omv, source_filesystem(args))
        if args.profile is not None:
            save_profile(args.profile, layout)
            print(f"Saved {len(layout)} Samba share(s) in vm_setup.omv_shares in {args.profile}.")
        else:
            print(json.dumps({"vm_setup": {"omv_shares": layout}}, ensure_ascii=False, indent=2))
        if skipped:
            print("Shares on other filesystems were skipped: " + ", ".join(map(repr, skipped)), file=sys.stderr)
    except subprocess.CalledProcessError as error:
        sys.exit(f"Export failed: {(error.stderr or '').strip() or 'a read-only SSH command failed'}")
    except KeyError as error:
        sys.exit(f"Export failed: OMV returned an incomplete or unresolved configuration reference {error}.")
    except (omv.InstallError, OSError, RuntimeError, ValueError, TypeError) as error:
        sys.exit(f"Export failed: {error}")


if __name__ == "__main__":
    main()
