#!/usr/bin/env python3
"""Provision the guests selected when this node's installer ISO was prepared."""

import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import create_vms
from install import checksum

JOB_DIR = Path(__file__).resolve().parents[1]
NODE_VERSION = "24.22.3"
NODE_SHA256 = "4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb"


def run(*command):
    subprocess.run(command, check=True)


def supports_homeassistant(node):
    return subprocess.run(
        [node, "-e", "const [major, minor] = process.versions.node.split('.').map(Number); "
         "process.exit(typeof WebSocket === 'function' && (major > 22 || (major === 22 && minor >= 4)) ? 0 : 1);"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def node_runtime(directory):
    system = shutil.which("node")
    if system and supports_homeassistant(system):
        return system
    cached = directory / f"node-{NODE_VERSION}"
    if cached.is_file() and supports_homeassistant(cached):
        return cached
    release = f"node-v{NODE_VERSION}-linux-x64"
    with TemporaryDirectory(prefix=".node-", dir=directory) as temporary:
        work = Path(temporary)
        archive = work / f"{release}.tar.xz"
        run("curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https",
            "--retry", "3", "--connect-timeout", "20", "--max-time", "600",
            "-o", archive, f"https://nodejs.org/dist/v{NODE_VERSION}/{archive.name}")
        if checksum(archive) != NODE_SHA256:
            raise create_vms.CreateError("The Node.js archive failed SHA-256 verification.")
        with tarfile.open(archive, "r:xz") as package, (work / "node").open("wb") as output:
            with package.extractfile(f"{release}/bin/node") as binary:
                shutil.copyfileobj(binary, output)
        pending = work / "node"
        pending.chmod(0o700)
        if not supports_homeassistant(pending):
            raise create_vms.CreateError("The verified Node.js runtime did not start.")
        pending.replace(cached)
    return cached


def read_config(target, vmid):
    return dict(line.split(": ", 1) for line in target.run("qm", "config", vmid, "--current").splitlines()
                if ": " in line)


def existing_owned_vms(target, plan, tag):
    inventory = target.json("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
    by_id = {int(item["vmid"]): item for item in inventory}
    by_name = {(item.get("name") or "").casefold(): int(item["vmid"]) for item in inventory}
    owned = {}
    for vm in plan:
        vmid, name = vm["vmid"], vm["name"]
        if name in by_name and by_name[name] != vmid:
            raise create_vms.CreateError(f"A different guest already uses the name {name}.")
        if vmid not in by_id:
            continue
        item = by_id[vmid]
        if item["type"] != "qemu" or item.get("name") != name:
            raise create_vms.CreateError(f"VM ID {vmid} is occupied by a different guest.")
        config = read_config(target, vmid)
        tags = set(re.split(r"[;,]", config.get("tags", "")))
        if tag not in tags:
            raise create_vms.CreateError(f"VM {vmid} ({name}) exists outside this first-boot job.")
        owned[vmid] = config
    return owned


def ensure_boot_order(target, vm, config):
    required = [vm["disk"]["slot"], *vm["media"]]
    if vm.get("efi"):
        required.append("efidisk0")
    if config is None or any(slot not in config for slot in required):
        raise create_vms.CreateError(f"VM {vm['vmid']} has incomplete disks or media. Inspect its Proxmox config.")
    order = f"order={vm['boot']}"
    if config.get("boot") != order:
        target.run("qm", "set", vm["vmid"], "--boot", order)


def ensure_started(target, vmid):
    if target.run("qm", "status", vmid) == "status: stopped":
        target.run("qm", "start", vmid)


def pci_groups(selector, devices):
    groups = set()
    for address in selector.split(";"):
        if not re.fullmatch(r"(?:[0-9a-f]{4}:)?[0-9a-f]{2}:[0-9a-f]{2}(?:\.[0-7])?", address):
            return set()
        if address.count(":") == 1:
            address = f"0000:{address}"
        functions = [devices / address] if "." in address else list(devices.glob(address + ".[0-7]"))
        if not functions:
            return set()
        for function in functions:
            group = function / "iommu_group"
            if not group.is_dir():
                return set()
            groups.add(("pci", group.resolve().name))
    return groups


def usb_ports(selector, devices):
    if re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*", selector):
        return {("usb", selector)} if (devices / selector / "idVendor").is_file() else set()
    if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", selector) or not devices.is_dir():
        return set()
    matches = set()
    for entry in devices.iterdir():
        try:
            identity = f"{(entry / 'idVendor').read_text().strip()}:{(entry / 'idProduct').read_text().strip()}"
        except OSError:
            continue
        if identity.lower() == selector:
            matches.add(("usb", entry.name))
    return matches


def passthrough_devices(slot, value, sysfs):
    options = value.split(",")
    selector = next((part[5:] for part in options if part.startswith("host=")), options[0]).lower()
    if slot.startswith("hostpci"):
        return pci_groups(selector, sysfs / "bus/pci/devices")
    return usb_ports(selector, sysfs / "bus/usb/devices")


def running_passthrough(target, sysfs):
    inventory = target.json("pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json")
    running = [guest for guest in inventory if guest.get("type") == "qemu" and guest.get("status") == "running"]
    claimed = set()
    if running:
        node = target.run("hostname", "-s")
        for guest in running:
            if guest.get("node") == node:
                config = read_config(target, guest["vmid"])
                for slot, value in config.items():
                    if create_vms.PCI_USB_SLOT.fullmatch(slot):
                        claimed.update(passthrough_devices(slot, value, sysfs))
    return claimed


def apply_passthrough(target, vm, config, hardware, sysfs=Path("/sys")):
    if config is None:
        return
    vmid = vm["vmid"]
    missing = [slot for slot in vm.get("passthrough", ()) if create_vms.PCI_USB_SLOT.fullmatch(slot) and slot not in config]
    available = {}
    for slot in missing:
        value = hardware.get(slot)
        matches = passthrough_devices(slot, value, sysfs) if value else set()
        if value is None:
            print(f"Skipped VM {vmid} {slot} because no mapping was saved.")
        elif not matches or (slot.startswith("usb") and len(matches) != 1):
            print(f"Skipped VM {vmid} {slot} because the recorded device is unavailable or ambiguous.")
        else:
            available[slot] = (value, matches)
    if not available:
        return
    if target.run("qm", "status", vmid) != "status: stopped":
        print(f"Skipped new PCI/USB mappings for VM {vmid} because it is running.")
        return
    try:
        claimed = running_passthrough(target, sysfs)
    except create_vms.CreateError:
        print(f"Skipped new PCI/USB mappings for VM {vmid} because the running guest assignments could not be checked.")
        return
    for slot, (value, devices) in available.items():
        if devices & claimed:
            print(f"Skipped VM {vmid} {slot} because a running VM is using the device.")
            continue
        try:
            target.run("qm", "set", vmid, f"--{slot}", value)
        except create_vms.CreateError:
            print(f"Skipped VM {vmid} {slot} because Proxmox rejected the mapping.")
        else:
            print(f"Applied the recorded {slot} mapping to VM {vmid}.")


def ensure_password(directory):
    path = directory / "ha-password"
    if not path.exists():
        with path.open("x") as output:
            output.write(secrets.token_urlsafe(24) + "\n")
    return path


def configure_ha(target, vm, config, job, directory):
    ensure_boot_order(target, vm, config)
    password = ensure_password(directory)
    node = node_runtime(directory)
    ensure_started(target, vm["vmid"])
    command = [node, directory / "setup_homeassistant/install.mjs", "configure", "--local-proxmox",
               "--vmid", str(vm["vmid"]), "--resume-if-needed", "--password-file", password,
               "--ssh-public-key", directory / "ssh.pub"]
    if job["xiaomi_home"]:
        command.append("--xiaomi-home")
    if not job["trusted_web_login"]:
        command.append("--no-trusted-web-login")
    run(*command)


def configure_omv(target, vm, config, job, directory, args):
    settings = vm["settings"]
    disk = vm["disk"]
    pm_args = ["--local-proxmox", "--vmid", str(vm["vmid"]), "--credentials-file", directory / "omv-credentials.txt"]
    command = [sys.executable, directory / "setup_openmediavault/install.py"]
    if config is None:
        hardware = {
            "settings": {name: value for name, value in settings.items() if name not in {"cores", "memory", "onboot"}},
            "boot_slot": disk["slot"], "boot_order": vm["boot"], "disk_options": disk.get("options", ""),
            "nic": vm["nic"].split(",", 1)[0],
        }
        more = [] if settings["onboot"] else ["--no-onboot"]
        run(*command, "install", *pm_args, "--name", vm["name"], "--storage", args.storage,
            "--iso-storage", args.iso_storage, "--bridge", args.bridge, "--cores", str(settings["cores"]),
            "--memory", str(settings["memory"]), "--boot-gb", str(disk["size"]),
            "--data-gb", str(job["omv_data_gb"]), "--ssh-public-key", directory / "ssh.pub",
            "--provision-tag", job["tag"], "--vm-hardware", json.dumps(hardware), *more)
        return
    data_slot = disk["slot"].removesuffix("0") + "1"
    if "setup-omv" not in re.split(r"[;,]", config.get("tags", "")) or (job["omv_data_gb"] and data_slot not in config):
        raise create_vms.CreateError(f"VM {vm['vmid']} has incomplete OpenMediaVault provisioning. Inspect its config.")
    ensure_boot_order(target, vm, config)
    onboot = str(settings["onboot"])
    if config.get("onboot", "0") != onboot:
        target.run("qm", "set", vm["vmid"], "--onboot", onboot)
    ensure_started(target, vm["vmid"])
    run(*command, "configure", *pm_args)


def provision(directory, target, catalog, job):
    args = SimpleNamespace(
        profiles=job["profiles"], vmid=None, name=None, cores=None, memory=None, disk_gb=None,
        no_onboot=False, bridge="vmbr0", storage="local-lvm", iso_storage="local",
        with_passthrough=False, hardware_file=directory / "vm-hardware.json", proxmox=None,
        image_dir=[], cache_dir=directory / "media", media_url=job["media_url"], provision_tag=job["tag"],
    )
    plan = create_vms.build_plan(catalog, args)
    hardware = create_vms.read_hardware(args.hardware_file) if args.hardware_file.exists() else {}
    for vm in plan:
        if vm["profile"] == "ha":
            vm["settings"]["agent"] = "enabled=1"
    owned = existing_owned_vms(target, plan, job["tag"])
    receipts = {vm["vmid"]: directory / f"vm-{vm['vmid']}-complete" for vm in plan}
    for vmid, receipt in receipts.items():
        if receipt.exists() and vmid not in owned:
            raise create_vms.CreateError(f"Completed VM {vmid} is missing. Inspect the first-boot state.")

    pending = [vm for vm in plan if vm["profile"] != "omv" and vm["vmid"] not in owned]
    if pending:
        create_vms.apply(catalog, pending, args)
        owned = existing_owned_vms(target, plan, job["tag"])

    for vm in plan:
        vmid, name = vm["vmid"], vm["profile"]
        if receipts[vmid].exists():
            continue
        config = owned.get(vmid)
        apply_passthrough(target, vm, config, hardware.get(name, {}))
        if name == "ha":
            configure_ha(target, vm, config, job, directory)
        elif name == "omv":
            configure_omv(target, vm, config, job, directory, args)
        else:
            ensure_boot_order(target, vm, config)
        receipts[vmid].touch()
    (directory / "vms-complete").touch()
    print("First-boot VM setup is complete.")


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise create_vms.CreateError("Run the first-boot VM job on the Proxmox node as root.")
    job = json.loads((JOB_DIR / "vm-job.json").read_text())
    catalog = json.loads(create_vms.CATALOG.read_text())
    with (JOB_DIR / "setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (JOB_DIR / "vms-complete").exists():
            provision(JOB_DIR, create_vms.Target(None), catalog, job)


if __name__ == "__main__":
    try:
        main()
    except (create_vms.CreateError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        detail = f"Guest setup exited with status {error.returncode}." if isinstance(error, subprocess.CalledProcessError) else str(error)
        sys.exit(f"VM setup failed: {detail}")
