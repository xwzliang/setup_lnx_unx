"""Regression checks for the installer-owned OMV data disk and Samba fix."""

import base64
from contextlib import redirect_stderr
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "setup_openmediavault"


def load(name):
    spec = spec_from_file_location("omv_" + name, HERE / (name + ".py"))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


install = load("install")
guest = load("configure_guest")


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


if __name__ == "__main__":
    unittest.main()
