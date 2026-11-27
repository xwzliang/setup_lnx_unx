"""Configure and verify the new OMV server. Run via the Proxmox guest agent."""

import fcntl
import json
import os
from pathlib import Path
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
    new_id = run("omv-env", "get", "OMV_CONFIGOBJECT_NEW_UUID").strip().split("=", 1)[1]
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
    share = by_field(SHARE, "sharedfolderref", folder["uuid"])
    if share is None:
        rpc("SMB", "setShare", uuid=new_id, enable=True, sharedfolderref=folder["uuid"], comment="",
            guest="no", readonly=False, browseable=True, recyclebin=False, recyclemaxsize=0,
            recyclemaxage=0, hidedotfiles=True, inheritacls=True, inheritpermissions=False,
            easupport=False, storedosattributes=False, hostsallow="", hostsdeny="", audit=False,
            extraoptions="")
    smb = read_model(SMB)
    update(SMB, {**smb, "enable": True, "workgroup": "WORKGROUP", "minprotocol": "SMB2"})
    run("omv-salt", "deploy", "run", "samba")
    run("/usr/bin/python3", "/usr/local/sbin/setup-omv-smb-aio.py", "--share", NAME)


def credentials(user, enable_share):
    path = STATE / "credentials"
    if not path.exists():
        web = secrets.token_urlsafe(24)
        smb = secrets.token_urlsafe(24)
        with path.open("x") as output:
            output.write(f"OMV web username: admin\nOMV web password: {web}\nSSH username: {user}\n")
            if enable_share:
                output.write(f"SMB username: {user}\nSMB password: {smb}\n")
    return dict(line.split(": ", 1) for line in path.read_text().splitlines())


def verify(identity, passwords):
    user = identity["user"]
    services = run("systemctl", "is-active", "ssh", "nginx", "qemu-guest-agent").splitlines()
    if services != ["active"] * 3:
        raise RuntimeError("SSH, nginx, or the Proxmox guest agent is inactive.")
    with urlopen("http://127.0.0.1/", timeout=10) as page:
        if page.status != 200 or b"openmediavault" not in page.read(65536).lower():
            raise RuntimeError("The OpenMediaVault web UI did not respond.")
    share = bool(identity["data_gb"])
    if share:
        run("systemctl", "is-active", "--quiet", "smbd")
        value = run("testparm", "-s", "--section-name=omv", "--parameter-name=aio write size").strip()
        if value != "0":
            raise RuntimeError("The SMB share did not inherit the aio write size setting.")
        with tempfile.NamedTemporaryFile(mode="w") as auth:
            auth.write(f"username = {user}\npassword = {passwords['SMB password']}\n")
            auth.flush()
            run("smbclient", "//127.0.0.1/omv", "-A", auth.name, "-c", "ls")
    routes = json.loads(run("ip", "-j", "-4", "route", "show", "default"))
    if not routes:
        raise RuntimeError("No default IPv4 route was assigned to the guest.")
    interfaces = json.loads(run("ip", "-j", "-4", "addr", "show", "dev", routes[0]["dev"], "scope", "global"))
    address = interfaces[0]["addr_info"][0]["local"]
    version = run("dpkg-query", "-W", "-f=${Version}", "openmediavault").strip()
    return {"user": user, "address": address, "version": version, "share": share}


def main():
    os.umask(0o077)
    identity = json.loads(Path("/etc/setup-omv.json").read_text())
    if os.geteuid() != 0 or identity["vmid"] != int(sys.argv[1]) or not (STATE / "packages-ready").is_file():
        raise RuntimeError("Expected a ready OpenMediaVault installer guest with the matching VM ID.")
    user = identity["user"]
    with (STATE / "configure.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        passwords = credentials(user, bool(identity["data_gb"]))
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
        result = verify(identity, passwords)
        ready.touch()
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError) as error:
        sys.exit(str(error))
