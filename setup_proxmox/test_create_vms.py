import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import create_vms as vms


class VmProfileTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(vms.CATALOG.read_text())
        self.args = SimpleNamespace(
            profiles=[], vmid=None, name=None, cores=None, memory=None, disk_gb=None,
            no_onboot=False, bridge="vmbr0", storage="local-lvm", iso_storage="local",
            with_passthrough=False,
        )

    def test_default_names_ids_and_boot_media(self):
        plan = vms.build_plan(self.catalog, self.args)
        self.assertEqual([(vm["vmid"], vm["name"]) for vm in plan], [
            (100, "ubuntu"), (101, "windows"), (102, "omv"),
            (103, "mac"), (104, "daily-ubuntu"), (105, "ha"),
        ])
        self.assertEqual([(vm["settings"]["cores"], vm["settings"]["memory"], vm["settings"]["cpu"],
                           vm["settings"]["sockets"], vm["settings"]["numa"]) for vm in plan], [
            (168, 512000, "host", 1, 0),
            (64, 204800, "host", 1, 0),
            (4, 16384, "x86-64-v2-AES", 1, 0),
            (4, 8192, "host", 1, 0),
            (32, 40960, "host", 1, 0),
            (2, 4096, "x86-64-v2-AES", 1, 0),
        ])
        self.assertEqual(plan[0]["disk"]["size"], 2548)
        self.assertEqual(plan[4]["media"]["ide2"]["image"], "ubuntu")
        self.assertTrue(self.catalog["media"][plan[5]["disk"]["image"]]["path"].endswith("18.4.qcow2.xz"))

    def test_occupied_id_or_name_stops_before_media_preparation(self):
        target = Mock()
        target.run.return_value = "0"
        target.json.return_value = [{"vmid": 999, "name": "WINDOWS"}]
        with self.assertRaisesRegex(vms.CreateError, "already exists"):
            vms.preflight(target, vms.build_plan(self.catalog, self.args), self.args)
        self.assertFalse(any(c.args[0] == "qm" for c in target.run.call_args_list))
        self.assertFalse(any(c.args[0] == "pvesm" for c in target.run.call_args_list))

    def test_appliance_import_uses_a_new_identity_and_sets_boot_last(self):
        self.args.profiles = ["ha"]
        self.args.vmid = 106
        self.args.name = "ha-test"
        plan = vms.build_plan(self.catalog, self.args)
        target = Mock()
        vms.create_vm(target, plan[0], {}, {"haos": ("/var/tmp/haos.qcow2", 6 * 1024**3)}, {}, self.args)
        create = target.run.call_args_list[0].args
        options = dict(zip(create[3::2], create[4::2]))
        self.assertEqual(create[:3], ("qm", "create", 106))
        self.assertEqual(options["--net0"], "virtio,bridge=vmbr0,firewall=1")
        self.assertEqual(options["--name"], "ha-test")
        self.assertIn("import-from=/var/tmp/haos.qcow2", options["--scsi0"])
        self.assertNotIn("--usb0", options)
        self.assertEqual(target.run.call_args_list[1].args, ("qm", "disk", "resize", 106, "scsi0", "32G"))
        self.assertEqual(target.run.call_args_list[-1].args, ("qm", "set", 106, "--boot", "order=scsi0;ide2;net0"))

    def test_exact_local_media_is_reused_and_a_bad_copy_is_rejected(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            asset = {"path": "Windows/test.iso", "sha256": hashlib.sha256(b"known iso").hexdigest()}
            local = directory / "test.iso"
            local.write_bytes(b"incorrect")
            with self.assertRaisesRegex(vms.CreateError, "exact verified image"):
                vms.find_media(asset, [directory], directory / "cache")
            local.write_bytes(b"known iso")
            self.assertEqual(vms.find_media(asset, [directory], directory / "cache"), local)

    def test_partition_check_allows_only_its_own_sata1_assignment(self):
        partition = "/dev/disk/by-partuuid/12345678-01"
        part_number = os.makedev(8, 1)
        root = MagicMock()
        parent = MagicMock()
        parent.is_block_device.return_value = True
        parent.stat.return_value.st_rdev = os.makedev(8, 0)
        part = MagicMock()
        part.__str__.return_value = partition
        part.is_block_device.return_value = True
        part.stat.return_value.st_rdev = part_number
        root.__truediv__.return_value = parent
        holders = Mock()
        holders.iterdir.return_value = ()
        cluster = Mock()
        owner = Mock(stem="102")
        owner.read_text.return_value = f"sata1: {partition},format=raw"
        other = Mock(stem="103")
        other.read_text.return_value = "scsi1: /dev/sda"
        cluster.glob.return_value = [owner]
        paths = {
            partition: part, "/dev": root, "/dev/sda": parent, "/etc/pve/nodes": cluster,
            f"/sys/dev/block/{os.major(part_number)}:{os.minor(part_number)}/holders": holders,
        }
        lsblk = json.dumps({"blockdevices": [{"type": "part", "mountpoints": [None], "pkname": "sda"}]})
        with patch("pathlib.Path", side_effect=paths.__getitem__), patch("subprocess.check_output", return_value=lsblk):
            with patch.object(sys, "argv", ["-c", partition]):
                with self.assertRaisesRegex(SystemExit, "attached to VM 102"):
                    exec(vms.RAW_DISK_CHECK, {})
            with patch.object(sys, "argv", ["-c", partition, "102"]):
                exec(vms.RAW_DISK_CHECK, {})
                cluster.glob.return_value = [owner, other]
                with self.assertRaisesRegex(SystemExit, "attached to VM 103"):
                    exec(vms.RAW_DISK_CHECK, {})


if __name__ == "__main__":
    unittest.main()
