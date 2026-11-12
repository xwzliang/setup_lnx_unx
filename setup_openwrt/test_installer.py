#!/usr/bin/env python3
"""Safety checks for automatic deployment/confirmation; never contacts a router."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from install_openclash_killswitch import Installer, interfaces, KILL_SWITCH_STATE, VERIFY, VERIFY_OFF, kill_switch_enabled


class FakeInstaller(Installer):
    def __init__(self, payload, existing=False, failure=None):
        super().__init__(argparse.Namespace(router="192.168.5.1", port=22,
            interfaces=None, backup_dir=Path("/tmp")), Path("/tmp/test-control"))
        self.payload = payload
        self.existing = existing
        self.failure = failure
        self.events = []

    def connect(self):
        self.client_ip = "192.168.5.103"
        self.router_ip = "192.168.5.1"

    def remote(self, command, data=None, timeout=30):
        if command.startswith("if test -d"):
            return "yes" if self.existing else "no"
        if command == KILL_SWITCH_STATE:
            return "0" if self.failure == "off" else "1"
        if command == "cat /etc/openclash-killswitch/interfaces":
            return "br-lan\nwireguard"
        if command.startswith("ip -4 route get"):
            return "192.168.5.103 dev br-lan src 192.168.5.1"
        if command.startswith("sha256sum"):
            return "different" if self.failure == "version" else hashlib.sha256(self.payload.read_bytes()).hexdigest()
        if command.endswith(" confirm"):
            self.events.append("confirm")
            return "Confirmed"
        raise AssertionError("Unexpected remote command: " + command)

    def script(self, source):
        return "br-lan\nwireguard"

    def probe(self, url):
        self.events.append("baseline")

    def upload_and_start(self, devices):
        self.events.append("install")
        if self.failure == "install": raise RuntimeError("installation failed")

    def wait_verified(self, devices):
        self.events.append("verify")
        if self.failure == "verify": raise RuntimeError("verification failed")

    def backup(self):
        self.events.append("backup")
        if self.failure == "backup": raise RuntimeError("backup failed")
        return Path("/tmp/private-backup.tar.gz")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.payload = Path(self.directory.name)/"payload.sh"
        self.payload.write_text("#!/bin/sh\nexit 0\n")

    def test_confirms_only_after_verification_and_backup(self):
        instance = FakeInstaller(self.payload)
        instance.run()
        self.assertEqual(instance.events[-4:], ["install", "verify", "backup", "confirm"])

    def test_failures_never_disarm_rollback(self):
        for failure in ("install", "verify", "backup"):
            with self.subTest(failure=failure):
                instance = FakeInstaller(self.payload, failure=failure)
                with self.assertRaises(RuntimeError): instance.run()
                self.assertNotIn("confirm", instance.events)

    def test_matching_existing_install_does_not_restart(self):
        instance = FakeInstaller(self.payload, existing=True)
        instance.run()
        self.assertEqual(instance.events, ["verify", "backup", "confirm"])

    def test_version_mismatch_is_not_overwritten_or_confirmed(self):
        instance = FakeInstaller(self.payload, existing=True, failure="version")
        with self.assertRaisesRegex(RuntimeError, "differs"): instance.run()
        self.assertEqual(instance.events, [])

    def test_disabled_existing_install_is_not_reenabled_or_retried(self):
        instance = FakeInstaller(self.payload, existing=True, failure="off")
        with self.assertRaisesRegex(RuntimeError, '--kill-switch on'):
            instance.run()
        self.assertEqual(instance.events, [])

    def test_invalid_state_is_rejected(self):
        instance = FakeInstaller(self.payload)
        with patch.object(instance, 'remote', return_value='unexpected'):
            with self.assertRaisesRegex(RuntimeError, 'Invalid installed'):
                kill_switch_enabled(instance)

    def test_off_verifier_rejects_leftover_guard(self):
        root = Path(self.directory.name)
        for path in ['etc/openclash-killswitch', 'etc/init.d', 'etc/openclash',
                     'proc/sys/net/ipv6/conf/all', 'bin']:
            (root/path).mkdir(parents=True, exist_ok=True)
        (root/'etc/openclash-killswitch/enabled').write_text('0\n')
        (root/'etc/openclash-killswitch/interfaces').write_text('br-lan\n')
        (root/'etc/openclash/test.yaml').write_text('ipv6: false\n')
        (root/'proc/sys/net/ipv6/conf/all/disable_ipv6').write_text('1\n')
        commands = {
            'etc/init.d/openclash-killswitch': '#!/bin/sh\nexit 0\n',
            'bin/ip': '''#!/bin/sh
case "$*" in
 '-4 route show table 354') echo 'default dev utun scope link';;
 '-4 route show table 51821') [ "$STALE" != table ] || echo 'prohibit default';;
 '-4 rule show') [ "$STALE" != rule ] || echo '11010: from all iif br-lan lookup 354';;
esac
exit 0
''',
            'bin/iptables': '#!/bin/sh\n[ "$STALE" != chain ] || echo "-N OC_KS_FORWARD"\nexit 0\n',
            'bin/uci': '#!/bin/sh\necho /etc/openclash/config/test.yaml\n',
        }
        for name, content in commands.items():
            (root/name).write_text(content)
            (root/name).chmod(0o755)
        source = VERIFY_OFF.replace('/etc/', str(root)+'/etc/').replace('/proc/', str(root)+'/proc/')
        env = {**os.environ, 'PATH': str(root/'bin')+':'+os.environ['PATH']}
        for stale in ['', 'rule', 'table', 'chain']:
            with self.subTest(stale=stale):
                result = subprocess.run(['sh'], input=source, text=True,
                                        capture_output=True, env={**env, 'STALE': stale})
                self.assertEqual(result.returncode == 0, not stale, result.stderr)
        for script in [VERIFY, VERIFY_OFF]:
            subprocess.run(['sh', '-n'], input=script, text=True, check=True)

    def test_enabled_guard_accepts_native_cn_routing_only_with_dns_protection_off(self):
        root = Path(self.directory.name)
        config = root/'runtime.yaml'
        settings = root/'settings.yaml'
        # Execute the actual Ruby policy check used by VERIFY, independent of
        # router-only route/firewall commands. The native selector is DIRECT-only.
        ruby = shlex.split(VERIFY[VERIFY.index('ruby -ryaml -e'):])[3]
        native = ('ipv6: false\nrules: ["GEOIP,CN,🎯 全球直连", "MATCH,新加坡"]\n'
                  'proxy-groups: [{name: "🎯 全球直连", type: select, proxies: [DIRECT]}]\n')
        config.write_text(native)
        for value, valid in [(None, False), ('{}', False), ('dns_protection: true', False), ('dns_protection: false', True)]:
            with self.subTest(settings=value):
                if value is None:
                    settings.unlink(missing_ok=True)
                else:
                    settings.write_text(value)
                result = subprocess.run(['ruby', '-ryaml', '-e', ruby, str(config), str(settings)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, valid, result.stderr)
        settings.write_text('dns_protection: false')
        config.write_text(native.replace('ipv6: false', 'ipv6: true'))
        result = subprocess.run(['ruby', '-ryaml', '-e', ruby, str(config), str(settings)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('IPv6 enabled', result.stderr)
        settings.unlink()
        config.write_text('ipv6: false\nrules: ["GEOIP,CN,DIRECT", "MATCH,新加坡"]\n')
        subprocess.run(['ruby', '-ryaml', '-e', ruby, str(config), str(settings)], check=True)

    def test_interface_names_cannot_inject_remote_commands(self):
        for values in ([], ["br-lan;reboot"], ["$(reboot)"], ["-i br-lan"]):
            with self.subTest(values=values), self.assertRaises(ValueError): interfaces(values)
        self.assertEqual(interfaces(["wireguard", "br-lan", "br-lan"]), ["br-lan", "wireguard"])

    def test_detached_runner_does_not_match_openclash_cleanup(self):
        instance = Installer(argparse.Namespace(router="192.168.5.1", port=22), Path("/tmp/test-control"))
        instance.payload = self.payload
        commands = []
        def remote(command, data=None, timeout=30):
            commands.append((command, data))
            if "mktemp" in command: return "/tmp/ks-deploy.ABC123"
            if "if test -f" in command: return "0"
            return ""
        with patch.object(instance, "remote", side_effect=remote):
            instance.upload_and_start(["br-lan"])
        launch = next(command for command, _ in commands if command.startswith("nohup"))
        self.assertNotIn("/etc/init.d/openclash", launch)
        self.assertIn("sh /tmp/ks-deploy.ABC123/run.sh", launch)
        runner = next(data for command, data in commands if command.endswith("run.sh"))
        self.assertIn('"$?"', runner)
        self.assertIn("install br-lan", runner)


if __name__ == "__main__":
    unittest.main()
