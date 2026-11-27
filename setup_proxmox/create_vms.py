#!/usr/bin/env python3
"""Create the lab's Proxmox VMs from their recorded defaults and clean media."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import quote, urljoin

from install import checksum

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "vm_profiles.json"
HARDWARE = Path.home() / ".config/setup-proxmox/vm-hardware.json"
CACHE = Path.home() / ".cache/setup-proxmox/vm-media"
IMAGE_ROOTS = (Path("/Volumes/DeepLearn/OS"), Path("/Volumes/omv/OS"))
STANDARD_SETTINGS = {"sockets": 1, "numa": 0, "ostype": "l26", "scsihw": "virtio-scsi-single", "onboot": 0}
PCI_USB_SLOT = re.compile(r"(?:hostpci|usb)[0-9]+")


class CreateError(Exception):
    pass


class Target:
    def __init__(self, host):
        self.host = host

    def invoke(self, *command, source=None):
        argv = list(map(str, command))
        if self.host is not None:
            argv = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
                    "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "--", self.host, shlex.join(argv)]
        return subprocess.run(
            argv,
            stdin=source if source is not None else subprocess.DEVNULL, text=True, capture_output=True,
        )

    def run(self, *command, source=None):
        result = self.invoke(*command, source=source)
        if result.returncode:
            label = " ".join(str(arg) for arg in command[:2])
            if "--args" in command:
                raise CreateError(f"{label} failed. Inspect the private QEMU settings on Proxmox.")
            detail = (result.stderr.strip() or result.stdout.strip())[-1600:]
            raise CreateError(f"{label} failed on {self.host or 'this node'}. {detail}".rstrip())
        return result.stdout.strip()

    def json(self, *command):
        return json.loads(self.run(*command))

    def exists(self, path):
        result = self.invoke("test", "-f", path)
        if result.returncode not in (0, 1):
            raise CreateError(f"Could not check the media file on {self.host}.")
        return result.returncode == 0

    def upload(self, local, remote):
        with local.open("rb") as contents:
            self.run("sh", "-c", 'cat > "$1"', "upload", remote, source=contents)

    def verify(self, path, digest):
        value = self.run("ionice", "-c3", "nice", "-n", "10", "sha256sum", "--", path).split(maxsplit=1)[0]
        if value != digest:
            raise CreateError(f"SHA-256 mismatch for {path} on {self.host}.")


def build_plan(catalog, args):
    profiles = catalog["vms"]
    selected = args.profiles or list(profiles)
    if len(selected) != len(set(selected)):
        raise CreateError("Each VM profile can be selected once.")
    if len(selected) != 1 and any(value is not None for value in
                                  (args.vmid, args.name, args.cores, args.memory, args.disk_gb)):
        raise CreateError("Select one profile when overriding its VM ID, name or resources.")
    plan = []
    for key in selected:
        vm = deepcopy(profiles[key])
        vm.update(profile=key, name=args.name or key)
        if args.vmid is not None:
            vm["vmid"] = args.vmid
        settings = {**STANDARD_SETTINGS, **vm["settings"]}
        for field in ("cores", "memory"):
            override = getattr(args, field)
            if override is not None:
                settings[field] = override
        if args.no_onboot:
            settings["onboot"] = 0
        if args.disk_gb is not None:
            vm["disk"]["size"] = args.disk_gb
        vm["settings"] = settings
        vm["nic"] = f"{vm.get('nic', 'virtio')},bridge={args.bridge},firewall=1"
        plan.append(vm)
    return plan


def display_plan(catalog, plan, args):
    for vm in plan:
        settings = ", ".join(f"{key}={value}" for key, value in vm["settings"].items())
        disk = vm["disk"]
        image = catalog["media"][disk["image"]]["path"] if "image" in disk else "blank"
        print(f"{vm['vmid']} {vm['name']} ({vm['profile']})")
        print(f"  {settings}")
        print(f"  net0={vm['nic']}  boot={vm['boot']}")
        print(f"  {disk['slot']}={disk['size']} GiB on {args.storage} ({image})")
        if vm.get("efi"):
            print(f"  efidisk0=4 MiB on {args.storage}")
        for slot, drive in vm["media"].items():
            image = catalog["media"][drive["image"]]["path"] if "image" in drive else "empty"
            print(f"  {slot}={image}")
        if vm.get("private_args"):
            print(f"  macOS QEMU arguments from {args.hardware_file}")
        if vm.get("passthrough"):
            description = "requested" if args.with_passthrough else "available with --with-passthrough"
            print(f"  Physical devices ({description}): {', '.join(vm['passthrough'])}")


def read_hardware(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise CreateError(f"Provide the private hardware file at {path} with mode 0600.")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise CreateError("The private hardware file must contain per-profile objects.")
    return data


def private_settings(plan, args, *, optional_passthrough=False):
    needs_args = any(vm.get("private_args") for vm in plan)
    if not needs_args and not (args.with_passthrough and any(vm.get("passthrough") for vm in plan)):
        return {}
    path = args.hardware_file
    if optional_passthrough and not needs_args and not (path.exists() or path.is_symlink()):
        return {}
    data = read_hardware(path)
    selected = {}
    for vm in plan:
        key = vm["profile"]
        fields = list(vm.get("passthrough", ())) if args.with_passthrough else []
        if vm.get("private_args"):
            fields.append("args")
        options = {}
        saved = data.get(key, {})
        if fields and not isinstance(saved, dict):
            raise CreateError(f"The private hardware file needs an object for {key}.")
        for field in fields:
            if optional_passthrough and field != "args" and field not in saved:
                continue
            value = saved.get(field)
            if not isinstance(value, str) or not value or any(char in value for char in "\r\n\0"):
                raise CreateError(f"The private hardware file needs {key}.{field}.")
            options[field] = value
        selected[key] = options
    return selected


def find_media(asset, roots, cache, media_url=None):
    relative = Path(asset["path"])
    paths = dict.fromkeys([*(root / item for root in roots for item in (relative, Path(relative.name))),
                          cache / relative.name])
    for file in paths:
        if file.is_file() and checksum(file) == asset["sha256"]:
            return file
    sources = [urljoin(media_url, quote(relative.as_posix()))] if media_url else []
    if asset.get("url"):
        sources.append(asset["url"])
    if not sources:
        raise CreateError(f"Provide the exact verified image {relative} with --image-dir.")
    cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    with TemporaryDirectory(prefix=".vm-media-", dir=cache) as directory:
        pending = Path(directory) / relative.name
        print(f"Downloading {relative.name}.", flush=True)
        for source in sources:
            transfer = subprocess.run(
                ["curl", "-fsSL", "--proto", "=http,https", "--proto-redir", "=https", "--retry", "2",
                 "--connect-timeout", "20", "--max-time", "3600", "-o", str(pending), source],
            )
            if transfer.returncode == 0 and checksum(pending) == asset["sha256"]:
                destination = cache / relative.name
                pending.replace(destination)
                return destination
    raise CreateError(f"Could not download and verify {relative.name}.")


def ensure_iso(target, asset, args):
    filename = Path(asset["path"]).name
    volume = f"{args.iso_storage}:iso/{filename}"
    destination = target.run("pvesm", "path", volume)
    if target.exists(destination):
        print(f"Verifying {volume} on Proxmox.", flush=True)
        target.verify(destination, asset["sha256"])
        return volume
    source = find_media(asset, [*args.image_dir, *IMAGE_ROOTS], args.cache_dir, getattr(args, "media_url", None))
    print(f"Uploading {filename} to {args.iso_storage}.", flush=True)
    target.run("mkdir", "-p", "--", str(Path(destination).parent))
    pending = target.run("mktemp", destination + ".upload.XXXXXXXX")
    try:
        target.upload(source, pending)
        target.verify(pending, asset["sha256"])
        target.run("chmod", "0644", "--", pending)
        target.run("mv", "-n", "--", pending, destination)
        if target.exists(pending):
            target.verify(destination, asset["sha256"])
    finally:
        target.run("rm", "-f", "--", pending)
    return volume


def prepare_disk(target, asset, stage, args):
    source = find_media(asset, [*args.image_dir, *IMAGE_ROOTS], args.cache_dir, getattr(args, "media_url", None))
    archive = f"{stage}/{Path(asset['path']).name}"
    print(f"Uploading {source.name} for disk import.", flush=True)
    target.upload(source, archive)
    target.verify(archive, asset["sha256"])
    target.run("xz", "-d", "--", archive)
    path = archive.removesuffix(".xz")
    info = target.json("qemu-img", "info", "--output=json", path)
    if info["format"] != "qcow2" or info.get("backing-filename"):
        raise CreateError("Expected a standalone qcow2 boot image.")
    return path, info["virtual-size"]


def check_storage(target, storage, content):
    info = target.json("pvesh", "get", f"/storage/{storage}", "--output-format", "json")
    if info.get("disable") or content not in info.get("content", "").split(","):
        raise CreateError(f"Storage {storage} must support {content}.")


def preflight(target, plan, args):
    if target.run("id", "-u") != "0":
        raise CreateError("Connect as root on the Proxmox node.")
    guests = target.json("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
    ids = {int(guest["vmid"]) for guest in guests}
    names = {(guest.get("name") or "").casefold() for guest in guests}
    for vm in plan:
        if vm["vmid"] in ids or vm["name"].casefold() in names:
            raise CreateError(f"VM {vm['vmid']} or guest name {vm['name']} already exists. No guests were changed.")
        target.run("pvesh", "get", "/cluster/nextid", "--vmid", vm["vmid"])
    target.run("ip", "link", "show", "dev", args.bridge)
    check_storage(target, args.storage, "images")
    if any("image" in drive for vm in plan for drive in vm["media"].values()):
        check_storage(target, args.iso_storage, "iso")


RAW_DISK_CHECK = r"""
from pathlib import Path
import json, os, re, subprocess, sys

device = Path(sys.argv[1])
if not device.is_block_device():
    sys.exit("The physical OMV partition could not be found.")
number = device.stat().st_rdev
mounts = json.loads(subprocess.check_output(
    ["lsblk", "-J", "-o", "TYPE,MOUNTPOINTS", str(device)], text=True))["blockdevices"]
holders = Path(f"/sys/dev/block/{os.major(number)}:{os.minor(number)}/holders")
if (len(mounts) != 1 or mounts[0]["type"] != "part" or mounts[0].get("children")
        or any(mounts[0]["mountpoints"] or []) or any(holders.iterdir())):
    sys.exit("The physical OMV partition is already in use on the Proxmox host.")
for config in Path("/etc/pve/nodes").glob("*/qemu-server/*.conf"):
    for value in re.findall(r"^(?:sata|scsi|virtio|ide|unused)\d+: (?:file=)?(/dev/[^,\n]+)", config.read_text(), re.M):
        other = Path(value)
        if value == str(device) or (other.is_block_device() and other.stat().st_rdev == number):
            sys.exit(f"The physical OMV partition is already attached to VM {config.stem}.")
"""


def check_omv_partition(target, mapping):
    path = mapping.split(",", 1)[0]
    if not re.fullmatch(r"/dev/disk/by-partuuid/[A-Fa-f0-9-]+", path):
        raise CreateError("The OMV data disk must use its exact /dev/disk/by-partuuid symlink.")
    target.run("python3", "-c", RAW_DISK_CHECK, path)
    return path


def check_physical_disk(target, private):
    for settings in private.values():
        if "sata1" in settings:
            check_omv_partition(target, settings["sata1"])


def create_vm(target, vm, media, imported, private, args):
    vmid = vm["vmid"]
    disk = vm["disk"]
    settings = {**vm["settings"], "net0": vm["nic"], "name": vm["name"], **private.get(vm["profile"], {})}
    if provision_tag := getattr(args, "provision_tag", None):
        settings["tags"] = provision_tag
    if vm.get("efi"):
        settings["efidisk0"] = f"{args.storage}:0,efitype=4m,pre-enrolled-keys=0"
    for slot, drive in vm["media"].items():
        settings[slot] = f"{media[drive['image']] if 'image' in drive else 'none'},{drive['options']}"
    disk_value = f"{args.storage}:{disk['size']}"
    if "image" in disk:
        path, image_bytes = imported[disk["image"]]
        disk_value = f"{args.storage}:0,import-from={path}"
    if disk.get("options"):
        disk_value += "," + disk["options"]
    settings[disk["slot"]] = disk_value
    options = [item for key, value in settings.items() for item in (f"--{key}", value)]
    try:
        target.run("qm", "create", vmid, *options)
        if "image" in disk and disk["size"] * 1024**3 > image_bytes:
            target.run("qm", "disk", "resize", vmid, disk["slot"], f"{disk['size']}G")
        target.run("qm", "set", vmid, "--boot", f"order={vm['boot']}")
    except CreateError as error:
        raise CreateError(f"Could not finish VM {vmid}. Inspect its config on Proxmox. {error}") from None
    print(f"Created VM {vmid} ({vm['name']}) in the stopped state.")


def apply(catalog, plan, args):
    target = Target(args.proxmox)
    preflight(target, plan, args)
    private = private_settings(plan, args)
    check_physical_disk(target, private)
    iso_keys = dict.fromkeys(drive["image"] for vm in plan for drive in vm["media"].values() if "image" in drive)
    disk_keys = dict.fromkeys(vm["disk"]["image"] for vm in plan if "image" in vm["disk"])
    stage = target.run("mktemp", "-d", "/var/tmp/setup-proxmox-vm.XXXXXXXX") if disk_keys else None
    try:
        media = {key: ensure_iso(target, catalog["media"][key], args) for key in iso_keys}
        imported = {key: prepare_disk(target, catalog["media"][key], stage, args) for key in disk_keys}
        for vm in plan:
            disk = vm["disk"]
            if "image" in disk and disk["size"] * 1024**3 < imported[disk["image"]][1]:
                raise CreateError(f"The boot disk for {vm['name']} is smaller than its source image.")
        preflight(target, plan, args)
        check_physical_disk(target, private)
        for vm in plan:
            create_vm(target, vm, media, imported, private, args)
    finally:
        if stage:
            target.run("rm", "-rf", "--", stage)


def bounded_int(minimum, maximum):
    def parse(value):
        if not re.fullmatch(r"[0-9]+", value) or not minimum <= int(value) <= maximum:
            raise argparse.ArgumentTypeError(f"Use a number between {minimum} and {maximum}.")
        return int(value)
    return parse


def arguments(catalog):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="*", metavar="PROFILE", help="VM names (default: all profiles)")
    parser.add_argument("--apply", action="store_true", help="create the selected VMs on Proxmox")
    parser.add_argument("--proxmox", default="pve", help="root SSH target (default pve)")
    parser.add_argument("--storage", default="local-lvm", help="VM disk storage")
    parser.add_argument("--iso-storage", default="local")
    parser.add_argument("--bridge", default="vmbr0")
    parser.add_argument("--image-dir", type=Path, action="append", default=[], help="additional local image directory")
    parser.add_argument("--cache-dir", type=Path, default=CACHE)
    parser.add_argument("--hardware-file", type=Path, default=HARDWARE, help="private QEMU and physical-device settings")
    parser.add_argument("--with-passthrough", action="store_true", help="use the recorded physical PCI, USB and OMV data disk assignments")
    parser.add_argument("--no-onboot", action="store_true", help="disable autostart for the selected VMs")
    parser.add_argument("--vmid", type=bounded_int(100, 999999999))
    parser.add_argument("--name", help="override the name of one selected profile")
    parser.add_argument("--cores", type=bounded_int(1, 512))
    parser.add_argument("--memory", type=bounded_int(256, 2_097_152), help="RAM in MiB for one VM")
    parser.add_argument("--disk-gb", type=bounded_int(1, 65536), help="boot disk GiB for one VM")
    args = parser.parse_args()
    unknown = set(args.profiles) - catalog["vms"].keys()
    if unknown:
        parser.error(f"Unknown profiles {', '.join(sorted(unknown))}. Choose from {', '.join(catalog['vms'])}.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:@[A-Za-z0-9][A-Za-z0-9._-]*)?", args.proxmox):
        parser.error("Invalid Proxmox SSH target.")
    for key in ("name", "storage", "iso_storage", "bridge"):
        value = getattr(args, key)
        if value is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            parser.error(f"Invalid --{key.replace('_', '-')}.")
    return args


def main():
    try:
        catalog = json.loads(CATALOG.read_text())
        args = arguments(catalog)
        plan = build_plan(catalog, args)
        display_plan(catalog, plan, args)
        if args.apply:
            apply(catalog, plan, args)
        else:
            print("Preview. Run with --apply to create these VMs.")
    except (CreateError, OSError, ValueError, KeyError) as error:
        sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
