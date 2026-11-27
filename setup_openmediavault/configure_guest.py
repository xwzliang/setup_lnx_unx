"""Configure and verify the new OMV server. Run via the Proxmox guest agent."""

import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from urllib.request import urlopen

STATE = Path("/var/lib/setup-omv")
MOUNT = "conf.system.filesystem.mountpoint"
POOL = "conf.service.mergerfs.pool"
FOLDER = "conf.system.sharedfolder"
SMB = "conf.service.smb"
SHARE = "conf.service.smb.share"
SSH = "conf.service.ssh"
NAME = "omv"
DISK_LABEL = "setup-omv-data"
FILESYSTEM_UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
EXISTING_MOUNT_OPTIONS = "defaults,nofail,noatime"


def run(*command, data=None):
    result = subprocess.run(command, input=data, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Passwords are only sent on stdin and errors from password setters
        # are deliberately omitted from the returned command output.
        detail = "" if data is not None else (result.stderr.strip() or result.stdout.strip())[-1600:]
        raise RuntimeError(f"{command[0]} {command[1]} failed ({result.returncode}). {detail}".rstrip())
    return result.stdout


def read_model(model):
    return json.loads(run("omv-confdbadm", "read", model))


def update(model, value):
    run("omv-confdbadm", "update", model, "-", data=json.dumps(value))


def rpc(service, method, **params):
    try:
        return json.loads(run("omv-rpc", "-u", "admin", service, method, json.dumps(params)))
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(f"{service}.{method}: {error}") from None


def by_field(model, field, value):
    entries = [entry for entry in read_model(model) if entry[field] == value]
    if len(entries) > 1:
        raise RuntimeError(f"Ambiguous {model} on the new guest.")
    return entries[0] if entries else None


def new_object_id():
    return run("omv-env", "get", "OMV_CONFIGOBJECT_NEW_UUID").strip().split("=", 1)[1]


def data_device(identity):
    columns = "PATH,TYPE,SERIAL,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS"
    devices = json.loads(run("lsblk", "-Jb", "-o", columns))["blockdevices"]
    disks = [d for d in devices if d["serial"] == f"omvdata{identity['vmid']}"]
    if (len(disks) != 1 or disks[0]["type"] != "disk" or disks[0].get("children")
            or disks[0]["size"] != identity["data_gb"] * 1024 ** 3):
        raise RuntimeError("Expected exactly one installer-created data disk with the matching size and serial.")
    return disks[0]


def mount_data(identity):
    disk = data_device(identity)
    path = disk["path"]
    if disk["fstype"] is None:
        signatures = json.loads(run("wipefs", "--no-act", "--json", path))["signatures"]
        if signatures or any(disk["mountpoints"] or []):
            raise RuntimeError("The data disk already contains a signature or mount.")
        run("mkfs.ext4", "-L", DISK_LABEL, path)
        run("udevadm", "settle", "--timeout=30")
        disk = data_device(identity)
    if disk["fstype"] != "ext4" or disk["label"] != DISK_LABEL or not disk["uuid"]:
        raise RuntimeError("The data disk is not the ext4 filesystem created by this installer.")
    identifier = f"/dev/disk/by-uuid/{disk['uuid']}"
    mount = by_field(MOUNT, "fsname", identifier) or rpc("FileSystemMgmt", "setMountPoint", id=identifier)
    run("omv-salt", "deploy", "run", "fstab")
    if subprocess.run(["mountpoint", "-q", mount["dir"]]).returncode:
        run("mount", mount["dir"])
    return mount


def ensure_share(identity, user):
    data = mount_data(identity)
    new_id = new_object_id()
    pool = by_field(POOL, "name", NAME) or rpc(
        "Mergerfs", "set", uuid=new_id, name=NAME, mntentref="", paths=data["dir"],
        createpolicy="epmfs", minfreespace=4, minfreespaceunit="G", options="defaults,cache.files=off",
    )
    if pool["paths"] != data["dir"]:
        raise RuntimeError("The existing pool points at another disk.")
    run("omv-salt", "deploy", "run", "mergerfs")
    mount = by_field(MOUNT, "uuid", pool["mntentref"])
    if not mount or run("findmnt", "-n", "--mountpoint", mount["dir"], "-o", "FSTYPE").strip() != "fuse.mergerfs":
        raise RuntimeError("The mergerfs pool is not mounted.")
    # Samba drops privileges to this account before entering the pool.
    pool_path = Path(mount["dir"])
    run("setfacl", "-m", f"u:{user}:--x", str(pool_path.parent))
    folder = by_field(FOLDER, "name", NAME) or rpc(
        "ShareMgmt", "set", uuid=new_id, name=NAME, reldirpath=NAME, comment="", mntentref=mount["uuid"], mode="770",
    )
    if folder["mntentref"] != mount["uuid"] or folder["reldirpath"].rstrip("/") != NAME:
        raise RuntimeError("The existing shared folder points outside the new pool.")
    share_path = pool_path / NAME
    run("chown", f"{user}:users", str(share_path))
    rpc("ShareMgmt", "setPrivileges", uuid=folder["uuid"], privileges=[{"type": "user", "name": user, "perms": 7}])
    ensure_smb_share(folder, new_id)
    deploy_samba([NAME])


def ensure_smb_share(folder, new_id, *, readonly=False, browseable=True):
    share = by_field(SHARE, "sharedfolderref", folder["uuid"])
    if share is None:
        rpc("SMB", "setShare", uuid=new_id, enable=True, sharedfolderref=folder["uuid"], comment="",
            guest="no", readonly=readonly, browseable=browseable, recyclebin=False, recyclemaxsize=0,
            recyclemaxage=0, hidedotfiles=True, inheritacls=True, inheritpermissions=False,
            easupport=False, storedosattributes=False, hostsallow="", hostsdeny="", audit=False,
            extraoptions="")
    return share


def deploy_samba(names):
    smb = read_model(SMB)
    update(SMB, {**smb, "enable": True, "workgroup": "WORKGROUP", "minprotocol": "SMB2"})
    run("omv-salt", "deploy", "run", "samba")
    for name in names:
        run("/usr/bin/python3", "/usr/local/sbin/setup-omv-smb-aio.py", "--share", name)


def existing_share_layout(shares):
    if not isinstance(shares, list) or not shares:
        raise RuntimeError("Supply a nonempty list of existing Samba shares.")
    names, paths = set(), set()
    layout = []
    for share in shares:
        if not isinstance(share, dict) or share.keys() - {"name", "path", "readonly", "browseable"}:
            raise RuntimeError("Invalid existing Samba share fields.")
        name, path = share.get("name"), share.get("path")
        readonly, browseable = share.get("readonly", False), share.get("browseable", True)
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_. -]{0,79}", name)
                or name != name.rstrip() or name.casefold() in names | {"global", "homes", "printers", "print$", "ipc$"}
                or not isinstance(path, str) or not path or path.startswith("/")
                or "\\" in path or any(ord(char) < 32 for char in path) or ".." in Path(path).parts
                or type(readonly) is not bool or type(browseable) is not bool):
            raise RuntimeError("Invalid name, relative path, or options in the existing Samba shares.")
        path = Path(path).as_posix()
        if path in paths:
            raise RuntimeError("Existing Samba shares must use distinct directories.")
        names.add(name.casefold())
        paths.add(path)
        layout.append({"name": name, "path": path, "readonly": readonly, "browseable": browseable})
    return layout


def mount_existing_data(filesystem_uuid):
    if not re.fullmatch(FILESYSTEM_UUID, filesystem_uuid):
        raise RuntimeError("Expected the ext4 filesystem UUID of the physical SATA disk.")
    identifier = f"/dev/disk/by-uuid/{filesystem_uuid}"
    directory = f"/srv/dev-disk-by-uuid-{filesystem_uuid}"
    run("udevadm", "settle", "--timeout=30")
    columns = "PATH,TYPE,FSTYPE,UUID,MOUNTPOINTS,MAJ:MIN"
    devices = json.loads(run("lsblk", "-Jl", "-o", columns))["blockdevices"]
    matching = [device for device in devices if device["uuid"] == filesystem_uuid]
    if (len(matching) != 1 or matching[0]["type"] != "disk" or matching[0]["fstype"] != "ext4"
            or set(filter(None, matching[0]["mountpoints"] or [])) - {directory}):
        raise RuntimeError("Expected exactly one ext4 SATA data disk with the supplied UUID and no other mount.")
    device = matching[0]
    if Path(identifier).resolve(strict=True) != Path(device["path"]).resolve(strict=True):
        raise RuntimeError("The ext4 UUID symlink does not resolve to the expected data disk.")
    already_mounted = directory in (device["mountpoints"] or [])
    target = Path(directory)
    if target.is_symlink() or (not already_mounted and target.exists()
                               and (not target.is_dir() or any(target.iterdir()))):
        raise RuntimeError("The OMV data mount directory is already in use.")
    if not already_mounted:
        header = run("env", "LC_ALL=C", "dumpe2fs", "-h", identifier)
        if not re.search(r"^Filesystem state:\s+clean\s*$", header, re.M) or "needs_recovery" in header.split():
            raise RuntimeError("The existing ext4 filesystem must be clean before mounting it.")
    mount = by_field(MOUNT, "fsname", identifier)
    create_mount = mount is None
    if create_mount:
        if by_field(MOUNT, "dir", directory) is not None:
            raise RuntimeError("OMV already assigned the data mount directory to another filesystem.")
        mount = rpc("FsTab", "set", uuid=new_object_id(), fsname=identifier, dir=directory,
                    type="ext4", opts=EXISTING_MOUNT_OPTIONS, freq=0, passno=0,
                    usagewarnthreshold=85, comment="Existing OMV data disk")
    if (mount["dir"], mount["type"], mount["opts"], mount["passno"], mount["hidden"]) != (
            directory, "ext4", EXISTING_MOUNT_OPTIONS, 0, False):
        raise RuntimeError("The existing OMV mount configuration differs from the expected data mount.")
    if create_mount or not already_mounted:
        run("omv-salt", "deploy", "run", "fstab")
    mounted = run("findmnt", "-n", "--mountpoint", directory, "-o", "MAJ:MIN,FSTYPE,OPTIONS").split()
    if (len(mounted) != 3 or mounted[:2] != [device["maj:min"], "ext4"]
            or not {"rw", "noatime"} <= set(mounted[2].split(","))):
        raise RuntimeError("The expected SATA filesystem is not mounted with the requested options.")
    return mount


def ensure_existing_shares(filesystem_uuid, layout, user):
    mount = mount_existing_data(filesystem_uuid)
    root = Path(mount["dir"]).resolve(strict=True)
    disk = root.stat().st_dev
    for share in layout:
        path = root / share["path"]
        if not path.is_dir() or path.resolve(strict=True) != path or path.stat().st_dev != disk:
            raise RuntimeError(f"The share directory {share['path']!r} must already exist on the data filesystem.")
    new_id = new_object_id()
    for share in layout:
        name = share["name"]
        relative = "/" if share["path"] == "." else share["path"] + "/"
        folder = by_field(FOLDER, "name", name)
        if folder is None:
            # Register only OMV metadata. ShareMgmt.set can create directories and change their permissions.
            update(FOLDER, {"uuid": new_id, "name": name, "comment": "", "mntentref": mount["uuid"],
                            "reldirpath": relative, "privileges": {"privilege": [
                                {"type": "user", "name": user, "perms": 5 if share["readonly"] else 7},
                            ]}})
            folder = by_field(FOLDER, "name", name)
        if (folder is None or folder["mntentref"] != mount["uuid"]
                or Path(folder["reldirpath"].strip("/")).as_posix() != share["path"]):
            raise RuntimeError(f"The existing shared folder {name!r} points to another location.")
        saved = ensure_smb_share(folder, new_id, readonly=share["readonly"], browseable=share["browseable"])
        if saved is not None and (not saved["enable"] or saved["guest"] != "no"
                                  or saved["readonly"] != share["readonly"] or saved["browseable"] != share["browseable"]):
            raise RuntimeError(f"The existing Samba share {name!r} has different access settings.")
    deploy_samba([share["name"] for share in layout])


def credentials(user, enable_share):
    path = STATE / "credentials"
    text = path.read_text() if path.exists() else ""
    updated = text
    if not text:
        web = secrets.token_urlsafe(24)
        updated = f"OMV web username: admin\nOMV web password: {web}\nSSH username: {user}\n"
    if enable_share and "\nSMB password: " not in updated:
        updated += f"SMB username: {user}\nSMB password: {secrets.token_urlsafe(24)}\n"
    if updated != text:
        with tempfile.TemporaryDirectory(dir=STATE) as temporary:
            pending = Path(temporary) / path.name
            pending.write_text(updated)
            pending.replace(path)
    return dict(line.split(": ", 1) for line in updated.splitlines())


def verify(identity, passwords, shares):
    user = identity["user"]
    services = run("systemctl", "is-active", "ssh", "nginx", "qemu-guest-agent").splitlines()
    if services != ["active"] * 3:
        raise RuntimeError("SSH, nginx, or the Proxmox guest agent is inactive.")
    with urlopen("http://127.0.0.1/", timeout=10) as page:
        if page.status != 200 or b"openmediavault" not in page.read(65536).lower():
            raise RuntimeError("The OpenMediaVault web UI did not respond.")
    if shares:
        run("systemctl", "is-active", "--quiet", "smbd")
        with tempfile.NamedTemporaryFile(mode="w") as auth:
            auth.write(f"username = {user}\npassword = {passwords['SMB password']}\n")
            auth.flush()
            for name in shares:
                value = run("testparm", "-s", f"--section-name={name}", "--parameter-name=aio write size").strip()
                if value != "0":
                    raise RuntimeError(f"The SMB share {name!r} did not inherit the aio write size setting.")
                run("smbclient", f"//127.0.0.1/{name}", "-A", auth.name, "-c", "ls")
    routes = json.loads(run("ip", "-j", "-4", "route", "show", "default"))
    if not routes:
        raise RuntimeError("No default IPv4 route was assigned to the guest.")
    interfaces = json.loads(run("ip", "-j", "-4", "addr", "show", "dev", routes[0]["dev"], "scope", "global"))
    address = interfaces[0]["addr_info"][0]["local"]
    version = run("dpkg-query", "-W", "-f=${Version}", "openmediavault").strip()
    return {"user": user, "address": address, "version": version, "shares": shares}


def main():
    os.umask(0o077)
    identity = json.loads(Path("/etc/setup-omv.json").read_text())
    if os.geteuid() != 0 or identity["vmid"] != int(sys.argv[1]) or not (STATE / "packages-ready").is_file():
        raise RuntimeError("Expected a ready OpenMediaVault installer guest with the matching VM ID.")
    user = identity["user"]
    reuse = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    layout = []
    shares = [NAME] if identity["data_gb"] else []
    if reuse is not None:
        if identity["data_gb"]:
            raise RuntimeError("Reuse requires an OMV guest provisioned with --data-gb 0.")
        layout = existing_share_layout(reuse["shares"])
        shares = [share["name"] for share in layout]
    with (STATE / "configure.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        passwords = credentials(user, bool(shares))
        ready = STATE / "configured"
        if not ready.exists():
            run("chpasswd", data=f"admin:{passwords['OMV web password']}\n")
            run("usermod", "-aG", "_ssh,users", user)
            settings = read_model(SSH)
            update(SSH, {**settings, "enable": True, "pubkeyauthentication": True,
                         "permitrootlogin": False, "passwordauthentication": False})
            run("omv-salt", "deploy", "run", "ssh")
            if identity["data_gb"]:
                password = passwords["SMB password"]
                run("smbpasswd", "-s", "-a", user, data=f"{password}\n{password}\n")
                ensure_share(identity, user)
        if reuse is not None:
            smb_account = STATE / "sata1-smb-account"
            if not smb_account.exists():
                password = passwords["SMB password"]
                run("smbpasswd", "-s", "-a", user, data=f"{password}\n{password}\n")
                smb_account.touch()
            ensure_existing_shares(reuse["uuid"], layout, user)
        result = verify(identity, passwords, shares)
        ready.touch()
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError) as error:
        sys.exit(str(error))
