"""Tests for the offline router profile used by the VM and USB installer."""

from argparse import Namespace
from ipaddress import IPv4Interface
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest

from immortalwrt_router_profile import CORE, add_file, load_profile, render_profile, write_profile


CONFIG = {
    'etc/config/network': b"""config interface 'lan'
 option ipaddr '192.168.5.1'
 option netmask '255.255.255.0'
config interface 'wan'
 option proto 'pppoe'
 option username 'saved-pppoe-user'
 option password 'saved-pppoe-password'
config interface 'wireguard'
 option proto 'wireguard'
 option private_key 'saved-wg-key'
""",
    'etc/config/dhcp': b"""config dnsmasq
 option noresolv '1'
 list server '127.0.0.1#7874'
config dhcp 'lan'
config host
 option ip '192.168.5.20'
""",
    'etc/config/firewall': b"""config defaults
 option fullcone '1'
config include
 option path '/etc/firewall.user'
config zone
 option name 'wan'
 option input 'REJECT'
""",
    'etc/config/system': b"""config system
 option hostname 'home-router'
 option timezone 'CST-8'
 option zonename 'Asia/Shanghai'
""",
    'etc/config/openclash': b"""config openclash 'config'
 option config_path '/etc/openclash/config/active.yaml'
config config_subscribe
 option convert_address 'http://192.168.5.1:15051/sub'
config config_subscribe
 option convert_address 'https://example.net/sub'
""",
    'etc/openclash/config/active.yaml': b'proxies: []\n',
    CORE: b'placeholder core for fixture',
}


class OfflineProfileTests(unittest.TestCase):
    def test_export_selects_only_router_settings_and_regular_openclash_files(self):
        with TemporaryDirectory() as directory:
            original = Path(directory) / 'backup.tar.gz'
            output = Path(directory) / 'profile.tar.gz'
            with tarfile.open(original, 'w:gz') as archive:
                for path, data in CONFIG.items():
                    add_file(archive, './' + path, data)
                add_file(archive, 'etc/shadow', b'old root hash')
                add_file(archive, 'etc/dropbear/dropbear_ed25519_host_key', b'old site key')
                add_file(archive, 'etc/openclash/custom/../../../tmp/escape', b'out of scope')
                entry = tarfile.TarInfo('etc/openclash/custom/outside')
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/shadow'
                archive.addfile(entry)
            write_profile(original, output)
            profile = load_profile(output)
            self.assertEqual(set(profile), set(CONFIG))
            self.assertEqual(profile[CORE][1], 0o700)
            with self.assertRaises(FileExistsError):
                write_profile(original, output)

    def test_production_profile_applies_saved_network_and_uses_a_local_converter(self):
        args = Namespace(lan=None, hostname=None, zone=None, timezone=None, isolated=False)
        profile = render_profile({path: (data, 0o600) for path, data in CONFIG.items()}, args)
        self.assertEqual(args.lan, IPv4Interface('192.168.5.1/24'))
        self.assertEqual(args.hostname, 'home-router')
        self.assertTrue(args.include_converter)
        self.assertIn(b'option proto pppoe', profile['etc/config/network'][0])
        self.assertIn(b'option private_key saved-wg-key', profile['etc/config/network'][0])
        self.assertIn(b'option ip 192.168.5.20', profile['etc/config/dhcp'][0])
        self.assertIn(b'option enable 1', profile['etc/config/openclash'][0])
        self.assertIn(b'http://127.0.0.1:15051/sub', profile['etc/config/openclash'][0])
        self.assertIn(b'https://example.net/sub', profile['etc/config/openclash'][0])
        self.assertNotIn(b'include', profile['etc/config/firewall'][0])
        self.assertIn('etc/nftables.d/20-setup-service-guard.nft', profile)

    def test_isolated_profile_uses_dhcp_wan_and_avoids_starting_wireguard(self):
        args = Namespace(lan=IPv4Interface('192.168.82.1/24'), hostname='test',
                         zone=None, timezone=None, isolated=True)
        profile = render_profile({path: (data, 0o600) for path, data in CONFIG.items()}, args)
        network = profile['etc/config/network'][0]
        self.assertIn(b'option proto dhcp', network)
        self.assertNotIn(b'saved-pppoe-', network)
        self.assertIn(b'option auto 0', network)
        self.assertEqual(args.lan, IPv4Interface('192.168.82.1/24'))
        self.assertEqual(args.hostname, 'test')


if __name__ == '__main__':
    unittest.main()
