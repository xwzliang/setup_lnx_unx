"""Regression checks for the installer-owned OMV data disk and Samba fix."""

import base64
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

HERE = Path(__file__).resolve().parents[1] / "setup_openmediavault"


def load(name):
    spec = spec_from_file_location("omv_" + name, HERE / (name + ".py"))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


install = load("install")
guest = load("configure_guest")
FILESYSTEM = "12345678-1234-1234-1234-123456789abc"
GPT = "abcdef01-2345-6789-abcd-ef0123456789"
SYSTEM_FILESYSTEM = "01234567-89ab-cdef-0123-456789abcdef"


def gpt_devices():
    data = {"path": "/dev/sda1", "type": "part", "fstype": "ext4", "uuid": FILESYSTEM,
            "mountpoints": [None], "maj:min": "8:1"}
    system = {"path": "/dev/sdb1", "type": "part", "fstype": "ext4", "uuid": SYSTEM_FILESYSTEM,
              "mountpoints": ["/"], "maj:min": "8:17"}
    return [
        {"path": "/dev/sda", "type": "disk", "pttype": "gpt", "ptuuid": GPT,
         "fstype": None, "uuid": None, "children": [data]},
        {"path": "/dev/sdb", "type": "disk", "pttype": "dos", "ptuuid": "deadbeef",
         "fstype": None, "uuid": None, "children": [system]},
    ]


class OpenMediaVaultTests(unittest.TestCase):
    def test_hardware_override_keeps_the_recorded_sata_slots_and_boot_order(self):
        self.assertEqual(install.vm_hardware(None)["boot_slot"], "scsi0")
        hardware = {"boot_slot": "sata0", "boot_order": "sata0;ide2;net0", "disk_options": ""}
        expected = {**install.VM_HARDWARE, **hardware}
        self.assertEqual(install.vm_hardware(json.dumps(hardware)), expected)

    def test_cloud_seed_contains_the_existing_samba_fix(self):
        args = SimpleNamespace(vmid=106, user="omvadmin", name="omv-new", data_gb=32,
                               ssh_public_key=None, timezone="Asia/Singapore")
        with patch.object(install, "authorized_key", return_value="ssh-ed25519 TEST"):
            seed = install.cloud_config(args)
        self.assertIn(base64.b64encode(install.SMB_AIO_HELPER.read_bytes()).decode(), seed)
        self.assertIn("ssh_pwauth: false", seed)

    def test_downloads_verified_image_once_and_reuses_local_cache(self):
        image = b"Debian cloud image fixture"
        digest = hashlib.sha512(image).hexdigest()

        def download(url, path, _seconds):
            if url.endswith("SHA512SUMS"):
                path.write_text(f"{digest}  {install.IMAGE}\n")
            else:
                path.write_bytes(image)
            return True

        with TemporaryDirectory() as stage, patch.object(install, "download", side_effect=download) as fetch:
            directory = Path(stage)
            self.assertEqual(install.cached_image(directory), (directory / install.IMAGE, digest))
            self.assertEqual(install.cached_image(directory), (directory / install.IMAGE, digest))
            self.assertEqual(fetch.call_count, 2)

    def test_first_boot_uses_readiness_marker_after_cloud_init_was_removed(self):
        args = SimpleNamespace(timeout=20)
        with patch.object(install, "guest", return_value={"exitcode": 0}) as command:
            install.wait_for_packages(args)
        command.assert_called_once_with(args, "/bin/sh", "-c", install.PACKAGE_STATUS)

    def test_reports_failed_bootstrap_without_waiting_for_cloud_init(self):
        args = SimpleNamespace(timeout=20)
        with patch.object(install, "guest", side_effect=[{"exitcode": 2}, {"exitcode": 1}]):
            with self.assertRaisesRegex(install.InstallError, "First boot failed"):
                install.wait_for_packages(args)

    def test_rejects_a_hostname_that_samba_cannot_use(self):
        argv = ["install.py", "install", "--vmid", "106", "--name", "omv-install-test"]
        with patch.object(sys, "argv", argv), redirect_stderr(StringIO()) as errors:
            with self.assertRaises(SystemExit):
                install.arguments()
        self.assertIn("at most 15 characters for Samba", errors.getvalue())

    def test_never_selects_a_wrong_disk_with_the_right_capacity(self):
        disks = {"blockdevices": [{"serial": "other", "size": 8 * 1024 ** 3, "type": "disk"}]}
        with patch.object(guest, "run", return_value=json.dumps(disks)):
            with self.assertRaisesRegex(RuntimeError, "installer-created data disk"):
                guest.data_device({"vmid": 106, "data_gb": 8})

    def test_refuses_to_format_a_disk_with_any_storage_signature(self):
        disk = {"path": "/dev/sdb", "fstype": None, "mountpoints": [None]}
        with patch.object(guest, "data_device", return_value=disk), patch.object(
                guest, "run", return_value=json.dumps({"signatures": [{"type": "gpt"}]})) as command:
            with self.assertRaisesRegex(RuntimeError, "already contains a signature"):
                guest.mount_data({"vmid": 106, "data_gb": 8})
        command.assert_called_once_with("wipefs", "--no-act", "--json", "/dev/sdb")

    def test_reuse_probes_only_the_active_raw_partition(self):
        partition = "/dev/disk/by-partuuid/12345678-01"
        with patch.object(install, "remote", return_value=SimpleNamespace(stdout=f"UUID={FILESYSTEM}\nTYPE=ext4\n")) as remote:
            self.assertEqual(install.sata1_disk_identity("pve", f"sata1: {partition},format=raw"), {"uuid": FILESYSTEM})
            self.assertEqual(remote.call_args_list, [
                call("pve", "test", "-b", partition),
                call("pve", "blkid", "-p", "-o", "export", "--", partition),
            ])
            remote.return_value.stdout = f"PTTYPE=gpt\nPTUUID={GPT.upper()}\n"
            self.assertEqual(install.sata1_disk_identity("pve", f"sata1: {partition}"), {"ptuuid": GPT})
            remote.reset_mock()
            with self.assertRaisesRegex(install.InstallError, "writable raw partition"):
                install.sata1_disk_identity("pve", "sata1: local-lvm:vm-102-disk-1")
            remote.assert_not_called()

    def test_configure_passes_the_gpt_identity_and_saved_shares_to_the_guest(self):
        shares = [{"name": "omv", "path": "omv", "readonly": False, "browseable": True}]
        args = SimpleNamespace(proxmox="pve", vmid=102, reuse_sata1=True, existing_shares=shares)
        response = {"address": "192.0.2.100", "version": "8.0", "user": "omvadmin", "shares": ["omv"]}
        with patch.object(install, "remote", return_value=SimpleNamespace(stdout="tags: setup-omv\n")), patch.object(
                install, "sata1_disk_identity", return_value={"ptuuid": GPT}), patch.object(
                install, "wait_for_packages"), patch.object(install, "save_credentials"), patch.object(
                install, "guest", side_effect=[{"exitcode": 0, "out-data": json.dumps(response)},
                                                {"exitcode": 0, "out-data": "credentials"}]) as command, redirect_stdout(StringIO()):
            install.configure(args)
        self.assertEqual(command.call_args_list[0].args[:4], (args, "/usr/bin/python3", "-", "102"))
        self.assertEqual(json.loads(command.call_args_list[0].args[4]), {"ptuuid": GPT, "shares": shares})

    def test_selects_the_existing_unpartitioned_ext4_disk(self):
        disk = {"path": "/dev/sda", "type": "disk", "fstype": "ext4", "uuid": FILESYSTEM}
        self.assertIs(guest.existing_data_device({"uuid": FILESYSTEM}, [disk]), disk)

    def test_reuse_stops_before_mounting_an_ambiguous_gpt_disk(self):
        for conflict, diagnostic in (("table", "exactly one guest disk"), ("partitions", "exactly one ext4"),
                                     ("filesystem", "also present")):
            with self.subTest(conflict=conflict):
                disks = gpt_devices()
                if conflict == "table":
                    disks[1].update(pttype="gpt", ptuuid=GPT)
                elif conflict == "partitions":
                    disks[0]["children"].append({"type": "part", "fstype": "ext4", "uuid": SYSTEM_FILESYSTEM})
                else:
                    disks[1]["children"][0]["uuid"] = FILESYSTEM
                with patch.object(guest, "run", side_effect=["", json.dumps({"blockdevices": disks})]) as run:
                    with self.assertRaisesRegex(RuntimeError, diagnostic):
                        guest.mount_existing_data({"ptuuid": GPT})
                self.assertEqual(run.call_args_list, [
                    call("udevadm", "settle", "--timeout=30"),
                    call(*guest.LIST_DATA_DEVICES),
                ])

    def test_reuse_checks_for_a_clean_ext4_filesystem_before_registering_mount(self):
        identifier = f"/dev/disk/by-uuid/{FILESYSTEM}"
        directory = f"/srv/dev-disk-by-uuid-{FILESYSTEM}"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            device, target = root / "data", root / "mount"
            device.touch()
            dirs = {identifier: device, "/dev/sda1": device, directory: target}
            devices = {"blockdevices": gpt_devices()}
            with patch.object(guest, "Path", side_effect=dirs.__getitem__), patch.object(
                    guest, "run", side_effect=["", json.dumps(devices), "Filesystem state: clean\nneeds_recovery"]) as run:
                with self.assertRaisesRegex(RuntimeError, "must be clean"):
                    guest.mount_existing_data({"ptuuid": GPT})
            self.assertEqual([entry.args[0] for entry in run.call_args_list], ["udevadm", "lsblk", "env"])
            with patch.object(guest, "Path", side_effect=dirs.__getitem__), patch.object(
                    guest, "run", side_effect=["", json.dumps(devices), "Filesystem state: clean",
                                               "", "8:1 ext4 rw,noatime"]) as run, patch.object(
                    guest, "by_field", return_value=None), patch.object(guest, "new_object_id", return_value="new"), patch.object(
                    guest, "rpc", return_value={"dir": directory, "type": "ext4", "opts": "defaults,nofail,noatime",
                                               "passno": 0, "hidden": False}) as rpc:
                guest.mount_existing_data({"ptuuid": GPT})
            rpc.assert_called_once_with("FsTab", "set", uuid="new", fsname=identifier, dir=directory, type="ext4",
                                        opts="defaults,nofail,noatime", freq=0, passno=0,
                                        usagewarnthreshold=85, comment="Existing OMV data disk")
            self.assertEqual([entry.args[0] for entry in run.call_args_list],
                             ["udevadm", "lsblk", "env", "omv-salt", "findmnt"])

    def test_existing_share_registration_preserves_directories_and_files(self):
        layout = guest.existing_share_layout([{"name": "omv", "path": "."},
                                              {"name": "Media", "path": "docs", "readonly": True}])
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "docs"
            path.mkdir()
            document = path / "file"
            document.write_text("existing data")
            modes = (path.stat().st_mode, document.stat().st_mode)
            config = {}

            def register(model, item):
                self.assertEqual(model, guest.FOLDER)
                config[item["name"]] = item

            with patch.object(guest, "mount_existing_data", return_value={"uuid": "mount", "dir": temporary}), patch.object(
                    guest, "new_object_id", return_value="new"), patch.object(
                    guest, "by_field", side_effect=lambda _model, _field, name: config.get(name)), patch.object(
                    guest, "update", side_effect=register), patch.object(guest, "ensure_smb_share", return_value=None) as smb, patch.object(
                    guest, "deploy_samba") as deploy, patch.object(guest, "run") as run:
                guest.ensure_existing_shares({"ptuuid": GPT}, layout, "omvadmin")
            self.assertEqual(config["omv"]["reldirpath"], "/")
            self.assertEqual(config["Media"]["reldirpath"], "docs/")
            self.assertEqual(config["Media"]["privileges"]["privilege"][0]["perms"], 5)
            smb.assert_called_with(config["Media"], "new", readonly=True, browseable=True)
            deploy.assert_called_once_with(["omv", "Media"])
            run.assert_not_called()
            self.assertEqual(document.read_text(), "existing data")
            self.assertEqual((path.stat().st_mode, document.stat().st_mode), modes)

    def test_invalid_share_paths_do_not_get_created(self):
        with self.assertRaisesRegex(RuntimeError, "relative path"):
            guest.existing_share_layout([{"name": "omv", "path": "../other"}])
        with TemporaryDirectory() as temporary, patch.object(
                guest, "mount_existing_data", return_value={"uuid": "mount", "dir": temporary}), patch.object(
                guest, "update") as update:
            layout = guest.existing_share_layout([{"name": "omv", "path": "absent"}])
            with self.assertRaisesRegex(RuntimeError, "must already exist"):
                guest.ensure_existing_shares({"uuid": FILESYSTEM}, layout, "omvadmin")
            update.assert_not_called()
            self.assertFalse((Path(temporary) / "absent").exists())

    def test_reuse_adds_smb_credentials_without_rotating_the_web_password(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(credentials_file=root / "host", reuse_sata1=True)
            with patch.object(guest, "STATE", root):
                first = guest.credentials("omvadmin", False)
                install.save_credentials(args, (root / "credentials").read_text())
                result = guest.credentials("omvadmin", True)
                credentials = (root / "credentials").read_text()
                install.save_credentials(args, credentials)
                self.assertEqual(guest.credentials("omvadmin", True), result)
            self.assertEqual(first["OMV web password"], result["OMV web password"])
            self.assertEqual((root / "host").read_text(), credentials)
            self.assertEqual((root / "host").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
