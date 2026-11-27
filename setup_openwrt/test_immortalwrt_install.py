"""Local tests for the clean installer's firmware and target checks."""

from argparse import Namespace
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import install_immortalwrt as installer


class ImmortalWrtInstallTests(unittest.TestCase):
    def test_cached_firmware_requires_the_official_digest(self):
        image = b'verified firmware'
        digest = hashlib.sha256(image).hexdigest()
        name = f'immortalwrt-{installer.RELEASE}-x86-64-generic-ext4-combined-efi.img.gz'
        with TemporaryDirectory() as directory, patch.dict(installer.CHECKSUMS, uefi=digest):
            path = Path(directory) / name
            path.write_bytes(image)
            self.assertEqual(installer.download_image(installer.RELEASE, 'uefi', path.parent), path)
            path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'Existing image failed the SHA-256 check'):
                installer.download_image(installer.RELEASE, 'uefi', path.parent)
            self.assertEqual(path.read_bytes(), b'corrupt')

    def test_linux_usb_rejects_mounted_or_internal_disks(self):
        device = '/dev/sdb'
        disk = {'path': device, 'type': 'disk', 'tran': 'usb', 'rm': True, 'ro': False,
                'size': 10_000_000_000, 'log-sec': 512, 'mountpoints': [None],
                'children': [{'type': 'part', 'mountpoints': [None]}]}
        with patch.object(installer.sys, 'platform', 'linux'), patch.object(installer, 'run') as lsblk:
            lsblk.side_effect = lambda *args, **kwargs: Mock(stdout=json.dumps({'blockdevices': [disk]}))
            self.assertEqual(installer.usb_info(device), (device, 10_000_000_000, 512))
            disk['children'][0]['mountpoints'] = ['/media/router']
            with self.assertRaisesRegex(ValueError, 'Unmount'):
                installer.usb_info(device)
            disk['tran'] = 'sata'
            with self.assertRaisesRegex(ValueError, 'removable USB'):
                installer.usb_info(device)

    def test_macos_usb_accepts_only_whole_external_usb_disks(self):
        disk = {'WholeDisk': True, 'Internal': False, 'BusProtocol': 'USB',
                'DeviceIdentifier': 'disk5', 'Size': 10_000_000_000, 'DeviceBlockSize': 512}
        with patch.object(installer.sys, 'platform', 'darwin'), patch.object(installer, 'run') as diskutil:
            diskutil.side_effect = lambda *args, **kwargs: Mock(stdout=plistlib.dumps(disk))
            self.assertEqual(installer.usb_info('/dev/disk5'), ('/dev/rdisk5', 10_000_000_000, 512))
            with self.assertRaisesRegex(ValueError, 'whole macOS disk'):
                installer.usb_info('/dev/disk5s1')
            disk['Internal'] = True
            with self.assertRaisesRegex(ValueError, 'external USB disk'):
                installer.usb_info('/dev/disk5')

    def test_corrupt_prepared_image_does_not_access_a_disk(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / 'router.img'
            image.write_bytes(b'wrong bytes')
            image.with_suffix('.img.sha256').write_text('0' * 64)
            with patch.object(installer.os, 'geteuid', return_value=0), patch.object(installer, 'usb_info') as info:
                with self.assertRaisesRegex(ValueError, 'Prepared image failed its SHA-256 check'):
                    installer.flash_usb(Namespace(image=image, device='/dev/disk5'))
                info.assert_not_called()

    def test_proxmox_checks_cluster_wide_vm_id_before_creating(self):
        with TemporaryDirectory() as directory:
            for command, script in {'pvesh': "echo '[{\"vmid\": 107, \"type\": \"lxc\"}]'",
                                    'qm': 'touch "$IMMORTALWRT_QM_LOG"'}.items():
                executable = Path(directory) / command
                executable.write_text('#!/bin/sh\n' + script + '\n')
                executable.chmod(0o700)
            marker = Path(directory) / 'qm-called'
            result = subprocess.run(
                ['bash', installer.PROXMOX_WORKER, '107', 'immortalwrt', 'local-lvm', 'uefi', '0' * 64],
                input=b'', capture_output=True,
                env={**os.environ, 'PATH': directory + os.pathsep + os.environ['PATH'],
                     'IMMORTALWRT_QM_LOG': str(marker)},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'VM ID is already in use: 107', result.stderr)
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
