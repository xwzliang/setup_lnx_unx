#!/usr/bin/env python3
"""Safety checks for automatic deployment/confirmation; never contacts a router."""
import argparse
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from install_openclash_killswitch import Installer, interfaces


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
