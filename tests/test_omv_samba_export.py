"""Fixture tests for reading and recording an OMV Samba share layout."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

from setup_openmediavault import export_samba_shares as export


UUID = "12345678-1234-1234-1234-123456789abc"
PTUUID = "abcdef01-2345-6789-abcd-ef0123456789"
SOURCE = f"/dev/disk/by-uuid/{UUID}"
DIRECTORY = f"/srv/dev-disk-by-uuid-{UUID}"
PARTITION = "/dev/disk/by-partuuid/12345678-01"


class SambaExportTests(unittest.TestCase):
    def setUp(self):
        self.models = {
            export.SHARE: [
                {"enable": True, "sharedfolderref": "root", "readonly": False, "browseable": True},
                {"enable": True, "sharedfolderref": "media", "readonly": False, "browseable": False},
                {"enable": False, "sharedfolderref": "disabled"},
            ],
            export.FOLDER: [
                {"uuid": "root", "name": "omv", "reldirpath": "/", "mntentref": "ext4"},
                {"uuid": "media", "name": "My Media", "reldirpath": "Videos/", "mntentref": "mergerfs"},
            ],
            export.MOUNT: [
                {"uuid": "ext4", "type": "ext4", "fsname": SOURCE, "dir": DIRECTORY},
                {"uuid": "mergerfs", "type": "fuse.mergerfs", "fsname": "pool", "dir": "/srv/mergerfs/media"},
            ],
            export.POOL: [{"mntentref": "mergerfs", "paths": f"{DIRECTORY}/Library=RO"}],
        }

    def remote(self, host, *command):
        if (host, command) == ("pve", ("qm", "config", "102", "--current")):
            return SimpleNamespace(stdout=f"sata1: {PARTITION},size=1024M")
        if (host, command) == ("pve", ("test", "-b", PARTITION)):
            return SimpleNamespace(stdout="")
        if (host, command) == ("pve", ("blkid", "-p", "-o", "export", "--", PARTITION)):
            return SimpleNamespace(stdout=f"PTTYPE=gpt\nPTUUID={PTUUID}\n")
        if (host, command) == ("omv", export.LIST_DATA_DEVICES):
            return SimpleNamespace(stdout=json.dumps({"blockdevices": [
                {"type": "disk", "pttype": "gpt", "ptuuid": PTUUID, "uuid": None, "children": [
                    {"type": "part", "fstype": "ext4", "uuid": UUID},
                ]},
            ]}))
        if host == "omv" and command[:4] == ("sudo", "-n", "omv-confdbadm", "read"):
            return SimpleNamespace(stdout=json.dumps(self.models[command[4]]))
        if (host, command) == ("omv", ("sudo", "-n", "findmnt", "--json", "--list", "--output", "TARGET,UUID,FSTYPE")):
            return SimpleNamespace(stdout=json.dumps({
                "filesystems": [{"target": DIRECTORY, "uuid": UUID, "fstype": "ext4"}],
            }))
        self.fail(f"Unexpected remote command: {host} {command}")

    def test_exports_sata1_root_and_single_mergerfs_branch_into_profile(self):
        with TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile.json"
            original = {"fqdn": "pve.example.test", "vm_setup": {"profiles": ["omv", "ha"], "omv_data_gb": 64}}
            profile.write_text(json.dumps(original))
            profile.chmod(0o600)
            with patch.object(sys, "argv", ["export", "--profile", str(profile)]), patch.object(
                    export.omv, "remote", side_effect=self.remote) as remote, redirect_stdout(StringIO()):
                export.main()
            expected = [
                {"name": "My Media", "path": "Library/Videos", "readonly": True, "browseable": False},
                {"name": "omv", "path": ".", "readonly": False, "browseable": True},
            ]
            original["vm_setup"]["omv_shares"] = expected
            self.assertEqual(json.loads(profile.read_text()), original)
            self.assertEqual(profile.stat().st_mode & 0o777, 0o600)
            inode = profile.stat().st_ino
            export.save_profile(profile, expected)
            self.assertEqual(profile.stat().st_ino, inode)
        self.assertEqual(remote.call_args_list, [
            call("pve", "qm", "config", "102", "--current"),
            call("pve", "test", "-b", PARTITION),
            call("pve", "blkid", "-p", "-o", "export", "--", PARTITION),
            call("omv", *export.LIST_DATA_DEVICES),
            call("omv", "sudo", "-n", "omv-confdbadm", "read", export.SHARE),
            call("omv", "sudo", "-n", "omv-confdbadm", "read", export.FOLDER),
            call("omv", "sudo", "-n", "omv-confdbadm", "read", export.MOUNT),
            call("omv", "sudo", "-n", "omv-confdbadm", "read", export.POOL),
        ])

    def test_preview_uses_filesystem_uuid_and_reports_other_mounts(self):
        self.models[export.MOUNT][0]["fsname"] = "/dev/disk/by-label/Data"
        self.models[export.MOUNT].append({"uuid": "other", "type": "ext4", "fsname": "/dev/sdc", "dir": "/srv/other"})
        self.models[export.FOLDER][1]["mntentref"] = "other"
        with patch.object(sys, "argv", ["export", "--filesystem-uuid", UUID]), patch.object(
                export.omv, "remote", side_effect=self.remote) as remote, redirect_stdout(StringIO()) as output, redirect_stderr(
                StringIO()) as stderr:
            export.main()
        self.assertEqual(json.loads(output.getvalue()), {"vm_setup": {"omv_shares": [
            {"name": "omv", "path": ".", "readonly": False, "browseable": True},
        ]}})
        self.assertIn("My Media", stderr.getvalue())
        self.assertTrue(all(entry.args[0] == "omv" for entry in remote.call_args_list))
        self.assertNotIn(call("omv", "sudo", "-n", "omv-confdbadm", "read", export.POOL), remote.call_args_list)

    def test_mixed_pool_leaves_the_saved_profile_untouched(self):
        self.models[export.POOL][0]["paths"] = f"{DIRECTORY}:/srv/other"
        with TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile.json"
            original = '{"vm_setup":{"profiles":["omv"],"omv_shares":[{"name":"old","path":"old"}]}}\n'
            profile.write_text(original)
            with patch.object(sys, "argv", ["export", "--profile", str(profile)]), patch.object(
                    export.omv, "remote", side_effect=self.remote):
                with self.assertRaisesRegex(SystemExit, "spans mergerfs branches"):
                    export.main()
            self.assertEqual(profile.read_text(), original)

    def test_rejects_shares_that_include_another_filesystem(self):
        self.models[export.MOUNT].append({
            "uuid": "nested", "type": "ext4", "fsname": "/dev/sdc", "dir": f"{DIRECTORY}/Nested",
        })
        with patch.object(export.omv, "remote", side_effect=self.remote):
            with self.assertRaisesRegex(export.omv.InstallError, "crosses another mount"):
                export.export_shares("omv", UUID)
