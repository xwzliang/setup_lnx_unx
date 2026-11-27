#!/usr/bin/env python3
"""Install and configure a fresh OpenMediaVault VM on Proxmox."""

import argparse
import base64
import fcntl
import hashlib
from io import BytesIO
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HERE = Path(__file__).resolve().parent
STATE = "/var/lib/setup-omv"
TAG = "setup-omv"
PACKAGE_STATUS = (
    f"test -f {STATE}/packages-ready && exit 0; "
    f"test -f {STATE}/packages-failed && exit 2; exit 1"
)
SMB_AIO_HELPER = HERE.parent / "packages/samba/scripts/linux/setup_omv_smb_aio.py"
IMAGE = "debian-13-generic-amd64.qcow2"
MEDIA = Path("/Volumes/DeepLearn/OS/omv")
MIRRORS = ("https://cloud.debian.org/images/cloud/trixie/latest",
           "https://cdimage.debian.org/cdimage/cloud/trixie/latest")


class InstallError(Exception):
    pass


def ssh_command(host, *command):
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
            "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "--", host, shlex.join(command)]


def remote(host, *command, data=None, check=True):
    return subprocess.run(
        ssh_command(host, *command),
        input=data or "", text=True, capture_output=True, check=check,
    )


def authorized_key(selected):
    if selected is not None:
        candidates = [selected]
    else:
        candidates = [Path.home() / ".ssh" / name for name in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub")]
    for path in candidates:
        if path.is_file():
            key = path.read_text().strip()
            if re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521) [A-Za-z0-9+/]+={0,2}(?: [^\r\n]+)?", key):
                return key
            if selected is not None:
                raise InstallError("Use an OpenSSH public key file.")
    raise InstallError("Provide an OpenSSH public key with --ssh-public-key.")


def cloud_config(args):
    identity = {"vmid": args.vmid, "user": args.user, "data_gb": args.data_gb}
    bootstrap = base64.b64encode((HERE / "bootstrap.sh").read_bytes()).decode()
    smb_aio = base64.b64encode(SMB_AIO_HELPER.read_bytes()).decode()
    # JSON scalars are YAML-compatible and keep SSH key comments literal.
    return f"""#cloud-config
hostname: {args.name}
timezone: {json.dumps(args.timezone)}
manage_etc_hosts: true
disable_root: true
ssh_pwauth: false
users:
  - name: {args.user}
    groups: [sudo]
    shell: /bin/bash
    lock_passwd: true
    sudo: ["ALL=(ALL) NOPASSWD:ALL"]
    ssh_authorized_keys:
      - {json.dumps(authorized_key(args.ssh_public_key))}
write_files:
  - path: /etc/setup-omv.json
    permissions: '0600'
    content: {json.dumps(json.dumps(identity))}
  - path: /usr/local/sbin/setup-omv-bootstrap
    permissions: '0700'
    encoding: b64
    content: {bootstrap}
  - path: /usr/local/sbin/setup-omv-smb-aio.py
    permissions: '0700'
    encoding: b64
    content: {smb_aio}
runcmd:
  - [/usr/local/sbin/setup-omv-bootstrap]
"""


def sha512(path):
    digest = hashlib.sha512()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url, path, seconds):
    return subprocess.run(["curl", "-fsSL", "--retry", "2", "--retry-all-errors", "--connect-timeout",
                           "12", "--max-time", str(seconds), "-o", str(path), url]).returncode == 0


def manifest_digest(manifest):
    for line in manifest.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] in (IMAGE, "*" + IMAGE) and re.fullmatch(r"[a-f0-9]{128}", fields[0]):
            return fields[0]
    return None


def cached_image(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    image = directory / IMAGE
    checksum = directory / (IMAGE + ".sha512")
    with (directory / ".setup-omv-image.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = sha512(image) if image.is_file() else None
        if existing and checksum.is_file() and checksum.read_text().strip() == existing:
            print(f"Using the verified Debian image at {image}.", flush=True)
            return image, existing
        with tempfile.TemporaryDirectory(prefix=".setup-omv-image-", dir=directory) as stage:
            manifest = Path(stage) / "SHA512SUMS"
            pending = Path(stage) / IMAGE
            for mirror in MIRRORS:
                if not download(f"{mirror}/SHA512SUMS", manifest, 60):
                    continue
                digest = manifest_digest(manifest.read_text())
                if not digest:
                    continue
                if digest != existing:
                    print(f"Downloading Debian 13 to {directory}.", flush=True)
                    if not download(f"{mirror}/{IMAGE}", pending, 900) or sha512(pending) != digest:
                        continue
                    if image.exists():
                        previous = directory / f"{IMAGE}.previous-{time.time_ns()}"
                        image.rename(previous)
                    pending.replace(image)
                manifest.write_text(digest + "\n")
                manifest.replace(checksum)
                return image, digest
    raise InstallError("The Debian image could not be downloaded and verified.")


def add_text(archive, name, text):
    source = BytesIO(text.encode())
    item = tarfile.TarInfo(name)
    item.size = source.getbuffer().nbytes
    archive.addfile(item, source)


def provision(args):
    seed = cloud_config(args)
    remote(args.proxmox, "pvesh", "get", "/cluster/nextid", "--vmid", str(args.vmid))
    members = remote(args.proxmox, "pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
    if any((member.get("name") or "").casefold() == args.name for member in json.loads(members.stdout)):
        raise InstallError("Another Proxmox guest has this name. Choose a distinct --name.")
    destination = credentials_path(args)
    if destination.exists() or destination.is_symlink():
        raise InstallError("The credentials destination already exists. Choose another --credentials-file.")
    directory = args.image_dir or (MEDIA if MEDIA.is_dir() else Path.home() / ".cache/setup-openmediavault/images")
    image, checksum = cached_image(directory)
    script = (HERE / "provision.sh").read_text()
    command = ssh_command(args.proxmox, "bash", "-c", script, "setup-omv", str(args.vmid), args.name,
                          args.storage, args.iso_storage, args.bridge, str(args.memory), str(args.cores),
                          str(args.boot_gb), str(args.data_gb), "0" if args.no_onboot else "1")
    print("Transferring the verified image and cloud-init seed to Proxmox.", flush=True)
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        try:
            with process.stdin, tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                add_text(archive, "checksum", checksum)
                add_text(archive, "user-data", seed)
                with image.open("rb") as source:
                    item = tarfile.TarInfo("image.qcow2")
                    item.size = os.fstat(source.fileno()).st_size
                    archive.addfile(item, source)
        except BrokenPipeError:
            pass
        if process.wait():
            raise InstallError(f"Proxmox provisioning failed with exit status {process.returncode}.")


def guest(args, *command, data=None, timeout=30):
    options = ["--timeout", str(timeout)]
    if data is not None:
        options += ["--pass-stdin", "1"]
    result = remote(args.proxmox, "qm", "guest", "exec", str(args.vmid), *options, "--", *command,
                    data=data, check=False)
    if result.returncode:
        raise InstallError(result.stderr.strip() or "The Proxmox guest agent did not respond.")
    reply = json.loads(result.stdout)
    if not reply.get("exited"):
        raise InstallError("The guest command is still running. Check the guest before retrying.")
    return reply


def wait_for_packages(args):
    print("Waiting for Debian first boot and OpenMediaVault packages.", flush=True)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            packages = guest(args, "/bin/sh", "-c", PACKAGE_STATUS).get("exitcode")
            if packages == 0:
                return
            state = None
            if packages != 2:
                report = guest(args, "/usr/bin/cloud-init", "status", "--format", "json")
                state = json.loads(report.get("out-data") or "{}").get("status")
        except (ValueError, InstallError):
            pass
        else:
            if packages == 2 or state in ("done", "error"):
                # Bootstrap may have finished between the agent calls.
                ready = guest(args, "/usr/bin/test", "-f", f"{STATE}/packages-ready")
                if ready.get("exitcode") == 0:
                    return
                raise InstallError("First boot failed. Inspect /var/log/cloud-init-output.log on the VM.")
        time.sleep(5)
    raise InstallError("Timed out waiting for first boot. Check the VM console or run configure again.")


def credentials_path(args):
    return args.credentials_file or (
        Path.home() / ".local/state/setup-openmediavault" / f"{args.proxmox}-{args.vmid}.txt"
    )


def save_credentials(args, credentials):
    destination = credentials_path(args)
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(destination, flags, 0o600), "w") as output:
            output.write(credentials)
    except FileExistsError:
        if (destination.is_symlink() or not destination.is_file()
                or destination.stat().st_mode & 0o077 or destination.read_text() != credentials):
            raise InstallError("The credentials destination already exists. Choose another --credentials-file.")
    return destination


def configure(args):
    config = remote(args.proxmox, "qm", "config", str(args.vmid)).stdout
    tags = re.search(r"^tags: (.*)$", config, re.MULTILINE)
    if not tags or TAG not in re.split("[;,]", tags[1]):
        raise InstallError("This VM was not created by setup_openmediavault.")
    wait_for_packages(args)
    code = (HERE / "configure_guest.py").read_text()
    result = guest(args, "/usr/bin/python3", "-", str(args.vmid), timeout=300, data=code)
    if result.get("exitcode") != 0:
        raise InstallError(result.get("err-data", "OpenMediaVault guest configuration failed.").strip())
    if result.get("out-truncated"):
        raise InstallError("OpenMediaVault guest returned incomplete verification data.")
    summary = json.loads(result["out-data"])
    credentials = guest(args, "/usr/bin/cat", f"{STATE}/credentials")
    if credentials.get("exitcode") != 0 or credentials.get("out-truncated") or not credentials.get("out-data"):
        raise InstallError("Could not retrieve the guest credentials.")
    destination = save_credentials(args, credentials["out-data"])
    address = ipaddress.IPv4Address(summary["address"])
    print(f"OpenMediaVault {summary['version']}: http://{address}")
    print(f"SSH: ssh {summary['user']}@{address}")
    if summary["share"]:
        print(f"SMB: smb://{address}/omv")
    print(f"Credentials saved at {destination}")


def between(minimum, maximum):
    def parse(value):
        if not re.fullmatch(r"[0-9]+", value) or not minimum <= int(value) <= maximum:
            raise argparse.ArgumentTypeError(f"Enter a number between {minimum} and {maximum}.")
        return int(value)
    return parse


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ("install", "configure"):
        command = commands.add_parser(operation)
        command.add_argument("--vmid", type=between(100, 999999999), required=True)
        command.add_argument("--proxmox", default="pve", help="root SSH target (default pve)")
        command.add_argument("--timeout", type=between(10, 7200), default=1800, help="first boot wait in seconds")
        command.add_argument("--credentials-file", type=Path, help="new private file for generated passwords")
        if operation == "install":
            command.add_argument("--name", default="omv")
            command.add_argument("--storage", default="local-lvm")
            command.add_argument("--iso-storage", default="local")
            command.add_argument("--image-dir", type=Path, help="local Debian image cache directory")
            command.add_argument("--bridge", default="vmbr0")
            command.add_argument("--memory", type=between(2048, 262144), default=16384, help="RAM in MiB")
            command.add_argument("--cores", type=between(1, 128), default=4)
            command.add_argument("--boot-gb", type=between(16, 16384), default=32)
            command.add_argument("--data-gb", type=between(0, 65536), default=32, help="new share disk in GiB, or 0 to skip")
            command.add_argument("--user", default="omvadmin", help="SSH and SMB user")
            command.add_argument("--timezone", default="Asia/Singapore")
            command.add_argument("--ssh-public-key", type=Path)
            command.add_argument("--no-onboot", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*(?:@[a-zA-Z0-9][a-zA-Z0-9._-]*)?", args.proxmox):
        parser.error("Invalid Proxmox SSH target.")
    if args.operation == "install":
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,14}", args.name) or args.name.endswith("-"):
            parser.error("Use a lowercase hostname of at most 15 characters for Samba.")
        if args.user in ("root", "admin", "debian", "nobody") or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.user):
            parser.error("Use a new local username for --user.")
        for label in ("storage", "iso_storage", "bridge"):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", getattr(args, label)):
                parser.error(f"Invalid {label.replace('_', ' ')}.")
        if 0 < args.data_gb < 8:
            parser.error("The mergerfs data disk must be at least 8 GiB, or 0 to skip it.")
        try:
            ZoneInfo(args.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            parser.error("Use an IANA time zone such as Asia/Singapore.")
    return args


def main():
    args = arguments()
    try:
        if args.operation == "install":
            provision(args)
        configure(args)
    except (InstallError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or "").strip() or f"Proxmox returned exit status {error.returncode}."
        else:
            detail = str(error)
        sys.exit(f"Error: {detail}")


if __name__ == "__main__":
    main()
