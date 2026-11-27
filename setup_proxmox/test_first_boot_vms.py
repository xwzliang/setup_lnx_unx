import base64
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import create_vms
import first_boot_vms as first_boot
import install


class FirstBootVmTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.catalog = json.loads(create_vms.CATALOG.read_text())
        self.job = {**install.load_vm_setup({"profiles": ["daily-ubuntu", "omv", "ha"]}), "tag": "setup-vms-test"}

    def test_payload_contains_only_selected_pci_usb_and_mac_arguments(self):
        with self.assertRaisesRegex(ValueError, "vm_setup.media_url"):
            install.load_vm_setup({})
        settings = install.load_vm_setup({"media_url": "http://media.example.test/OS"})
        hardware = self.directory / "hardware.json"
        hardware.write_text(json.dumps({
            "mac": {"args": "-smbios type=2"}, "omv": {"sata1": "private-disk"},
            "windows": {"hostpci0": "0000:81:00,pcie=1", "usb0": "host=1-1.1,usb3=1"},
            "ha": {"usb0": "host=1234:5678", "usb1": "host=1234:5679"},
        }))
        hardware.chmod(0o600)
        script = install.first_boot_script({"repository": "enterprise", "upgrade": False, "vm_setup": settings},
                                          "ssh-ed25519 TEST", hardware)
        marker = "SETUP_VM_PAYLOAD"
        encoded = script.split(f"<<'{marker}' | tar -xzf - -C \"$job\"\n", 1)[1].split(f"\n{marker}\n", 1)[0]
        with tarfile.open(fileobj=BytesIO(base64.b64decode(encoded)), mode="r:gz") as bundle:
            self.assertEqual(set(bundle.getnames()), {*install.VM_SETUP_FILES, "vm-job.json", "ssh.pub", "vm-hardware.json"})
            for name in install.VM_SETUP_FILES:
                self.assertEqual(bundle.extractfile(name).read(), (install.HERE.parent / name).read_bytes())
            self.assertEqual(json.load(bundle.extractfile("vm-hardware.json")), {
                "mac": {"args": "-smbios type=2"},
                "windows": {"hostpci0": "0000:81:00,pcie=1", "usb0": "host=1-1.1,usb3=1"},
                "ha": {"usb0": "host=1234:5678"},
            })
            job = json.load(bundle.extractfile("vm-job.json"))
            self.assertEqual(job["profiles"], list(self.catalog["vms"]))
            self.assertEqual(job["media_url"], "http://media.example.test/OS/")

    def test_available_passthrough_preserves_options_and_skips_busy_or_ambiguous_devices(self):
        sysfs = self.directory / "sys"
        iommu = sysfs / "kernel/iommu_groups/7"
        iommu.mkdir(parents=True)
        for function in ("0000:81:00.0", "0000:81:00.1"):
            pci = sysfs / "bus/pci/devices" / function
            pci.mkdir(parents=True)
            (pci / "iommu_group").symlink_to(iommu)
        for port, product in (("1-1.1", "0001"), ("1-1.2", "1234"), ("1-1.3", "1234"), ("1-2", "0002")):
            device = sysfs / "bus/usb/devices" / port
            device.mkdir(parents=True)
            (device / "idVendor").write_text("abcd\n")
            (device / "idProduct").write_text(product + "\n")
        target = Mock()
        target.run.side_effect = ["status: stopped", "pve-new", "usb0: host=abcd:0002", "", ""]
        target.json.return_value = [{"type": "qemu", "node": "pve-new", "status": "running", "vmid": 110}]
        vm = {"vmid": 101, "passthrough": ["hostpci0", "hostpci1", "usb0", "usb1", "usb2", "usb3", "sata1"]}
        hardware = {
            "hostpci0": "0000:81:00,pcie=1", "hostpci1": "0000:82:00,pcie=1",
            "usb0": "host=1-1.1,usb3=1", "usb1": "host=abcd:1234",
            "usb2": "host=1-2", "usb3": "host=1-3", "sata1": "raw-disk",
        }
        first_boot.apply_passthrough(target, vm, {"usb3": "host=1-4"}, hardware, sysfs)
        updates = [call.args for call in target.run.call_args_list if call.args[:2] == ("qm", "set")]
        self.assertEqual(updates, [
            ("qm", "set", 101, "--hostpci0", "0000:81:00,pcie=1"),
            ("qm", "set", 101, "--usb0", "host=1-1.1,usb3=1"),
        ])

    def test_provisioning_resumes_ha_without_recreating_its_vm_or_rerunning_omv(self):
        hardware = self.directory / "vm-hardware.json"
        hardware.write_text(json.dumps({"ha": {"usb0": "host=1234:5678"}}))
        hardware.chmod(0o600)
        configs = {}
        commands = []
        credentials = []
        running = set()

        def inventory(*_):
            return [{"vmid": vmid, "name": config["name"], "type": "qemu"} for vmid, config in configs.items()]

        def qemu(*command):
            _, action, vmid, *_ = command
            if action == "config":
                return "\n".join(f"{key}: {value}" for key, value in configs[vmid].items())
            if action == "status":
                return "status: running" if vmid in running else "status: stopped"
            if action == "start":
                self.assertEqual(configs[vmid]["usb0"], "host=1234:5678")
                running.add(vmid)
                return ""
            if action == "set":
                self.assertEqual(command[3], "--usb0")
                configs[vmid]["usb0"] = command[4]
                return ""
            raise AssertionError(command)

        def create(_catalog, pending, args):
            for vm in pending:
                configs[vm["vmid"]] = {
                    "name": vm["name"], "tags": args.provision_tag, "boot": f"order={vm['boot']}",
                    vm["disk"]["slot"]: "disk", **{slot: "media" for slot in vm["media"]},
                }
                if vm.get("efi"):
                    configs[vm["vmid"]]["efidisk0"] = "efi"
                if vm["profile"] == "ha":
                    self.assertEqual(vm["settings"]["agent"], "enabled=1")

        def guest_setup(*command):
            commands.append(command)
            if command[2] == "install":
                self.assertIn("--local-proxmox", command)
                self.assertEqual(command[command.index("--provision-tag") + 1], self.job["tag"])
                self.assertEqual(command[command.index("--cores") + 1], "4")
                self.assertEqual(command[command.index("--memory") + 1], "16384")
                self.assertEqual(command[command.index("--boot-gb") + 1], "32")
                self.assertEqual(json.loads(command[command.index("--vm-hardware") + 1]), {
                    "settings": {"sockets": 1, "numa": 0, "ostype": "l26", "scsihw": "virtio-scsi-single",
                                 "cpu": "x86-64-v2-AES", "startup": "order=1"},
                    "boot_slot": "sata0", "boot_order": "sata0;ide2;net0", "disk_options": "", "nic": "virtio",
                })
                configs[102] = {"name": "omv", "tags": f"setup-omv;{self.job['tag']}", "sata0": "disk",
                                "ide2": "seed", "sata1": "data"}
            else:
                self.assertIn("--resume-if-needed", command)
                password = command[command.index("--password-file") + 1]
                credentials.append(password.read_bytes())
                if len(credentials) == 1:
                    raise subprocess.CalledProcessError(1, command)

        target = Mock()
        target.json.side_effect = inventory
        target.run.side_effect = qemu
        with patch.object(create_vms, "apply", side_effect=create) as create_pending, patch.object(
                first_boot, "run", side_effect=guest_setup), patch.object(
                first_boot, "node_runtime", return_value="node"), patch.object(
                first_boot, "passthrough_devices", return_value={("usb", "1-1")}):
            with self.assertRaises(subprocess.CalledProcessError):
                first_boot.provision(self.directory, target, self.catalog, self.job)
            self.assertTrue((self.directory / "vm-102-complete").exists())
            self.assertFalse((self.directory / "vms-complete").exists())
            first_boot.provision(self.directory, target, self.catalog, self.job)
        self.assertEqual(create_pending.call_count, 1)
        self.assertEqual([command[2] for command in commands], ["install", "configure", "configure"])
        self.assertEqual(credentials[0], credentials[1])
        self.assertEqual(running, {105})
        self.assertTrue((self.directory / "vms-complete").exists())

    def test_existing_vm_without_the_job_tag_blocks_any_guest_changes(self):
        target = Mock()
        target.json.return_value = [{"vmid": 105, "name": "ha", "type": "qemu"}]
        target.run.return_value = "name: ha\ntags: unrelated"
        with patch.object(create_vms, "apply") as create_pending, patch.object(first_boot, "run") as guest_setup:
            with self.assertRaisesRegex(create_vms.CreateError, "outside this first-boot job"):
                first_boot.provision(self.directory, target, self.catalog, self.job)
        create_pending.assert_not_called()
        guest_setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
