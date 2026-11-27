"""Local checks for the Proxmox installer profile and ISO validation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import install


class InstallTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.path = Path(workspace.name) / 'profile.json'
        self.profile = json.loads((install.HERE / 'profile.example.json').read_text())
        self.profile['disk']['id'] = 'PVE-TEST-OS'

    def load(self):
        self.path.write_text(json.dumps(self.profile))
        return install.load_profile(self.path)

    def test_answer_selects_exact_disk_and_management_nic(self):
        profile = self.load()
        answer = install.answer_file(profile, '$6$example$hash', 'ssh-ed25519 public-key')
        self.assertIn('filter.ID_SERIAL_SHORT = "PVE-TEST-OS"', answer)
        self.assertIn('filter.ID_NET_NAME_MAC = "enx525400123456"', answer)
        self.assertIn('root-password-hashed = "$6$example$hash"', answer)
        self.assertIn('root-ssh-keys = ["ssh-ed25519 public-key"]', answer)
        self.assertIn('[first-boot]\nsource = "from-iso"', answer)
        self.assertNotIn('disk-list', answer)

    def test_rejects_disk_globs_and_kernel_names_by_property(self):
        for disk in (
            {'property': 'ID_SERIAL_SHORT', 'id': 'PVE-*'},
            {'property': 'ID_SERIAL_SHORT', 'id': 'REPLACE-WITH-EXACT-DISK-SERIAL'},
            {'property': 'DEVNAME', 'id': '/dev/sda'},
        ):
            with self.subTest(disk=disk):
                self.profile['disk'] = disk
                with self.assertRaisesRegex(ValueError, 'disk'):
                    self.load()

    def test_rejects_network_settings_that_cannot_reach_gateway(self):
        self.profile['network']['gateway'] = '192.168.6.1'
        with self.assertRaisesRegex(ValueError, 'gateway'):
            self.load()
        self.profile['network']['gateway'] = '192.168.5.1'
        self.profile['network']['mac'] = '01:00:00:00:00:42'
        with self.assertRaisesRegex(ValueError, 'unicast'):
            self.load()

    def test_hashes_password_through_stdin(self):
        path = self.path.with_name('password')
        path.write_text('temporary-passphrase\n')
        with patch.object(install, 'run') as command:
            hashed = '$6$salt$' + 'H' * 86
            command.return_value.stdout = hashed + '\n'
            self.assertEqual(install.password_hash(path), hashed)
            command.assert_called_once_with(
                'openssl', 'passwd', '-6', '-stdin', input='temporary-passphrase\n',
                capture_output=True, text=True,
            )

    def test_rejects_a_corrupt_local_iso(self):
        iso = self.path.with_name(install.ISO_NAME)
        iso.write_bytes(b'invalid ISO')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            install.stock_iso(iso, self.path.parent)


if __name__ == '__main__':
    unittest.main()
