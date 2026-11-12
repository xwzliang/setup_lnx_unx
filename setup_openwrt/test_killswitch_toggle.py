"""Exercise kill-switch mode changes against a fake UCI/kernel command boundary."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


class KillSwitchToggleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "state"
        self.base.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "commands.jsonl"
        self.config = self.root / "firewall.json"
        self.script = self.root / "killswitch.sh"
        self.firewall = self.root / "firewall-service"
        self.base.joinpath("interfaces").write_text("br-lan\ndocker0\n")
        source = Path(__file__).with_name("openclash-killswitch.sh").read_text()
        source = source.replace("BASE=/etc/openclash-killswitch", f"BASE='{self.base}'")
        source = source.replace("/var/lock", str(self.root / "lock"))
        source = source.replace("/etc/init.d/firewall", str(self.firewall))
        source = source.replace("/proc/sys/net/ipv6/conf", str(self.root / "no-proc"))
        self.script.write_text(source)
        self.firewall.write_text(f'#!/bin/sh\nexec sh "{self.script}" apply\n')
        self.firewall.chmod(0o700)
        mock = self.bin / "mock"
        mock.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
command = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["MOCK_LOG"], "a") as handle:
    handle.write(json.dumps([command, *args]) + "\\n")
if command == "id":
    print("0")
elif command == "ip":
    if "del" in args:
        sys.exit(1)
    if args == ["-4", "rule", "show"]:
        print("0: from all lookup local")
    if args[:6] == ["-4", "route", "show", "table", "main", "dev"]:
        print("192.168.5.0/24 proto kernel scope link")
elif command == "iptables":
    if "-D" in args or "-C" in args:
        sys.exit(1)
elif command == "uci":
    path = pathlib.Path(os.environ["MOCK_CONFIG"])
    if "-c" in args:
        index = args.index("-c")
        path = pathlib.Path(args[index + 1]) / "firewall"
        del args[index:index + 2]
    args = [arg for arg in args if arg != "-q"]
    config = json.loads(path.read_text())
    if args[0] == "show":
        for key, value in config.items():
            print(key + "=" + value)
    elif args[0] == "get":
        if args[1] not in config:
            sys.exit(1)
        print(config[args[1]])
    elif args[0] == "set":
        key, value = args[1].split("=", 1)
        config[key] = value
        path.write_text(json.dumps(config))
    elif args[0] == "delete":
        config.pop(args[1], None)
        path.write_text(json.dumps(config))
''')
        mock.chmod(0o700)
        for command in ("id", "ip", "iptables", "uci", "flock"):
            (self.bin / command).symlink_to(mock)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        MOCK_LOG=str(self.log), MOCK_CONFIG=str(self.config))
        self.original = {
            "firewall.@defaults[0]": "defaults",
            "firewall.@defaults[0].forward": "REJECT",
            "firewall.@defaults[0].flow_offloading": "1",
            "firewall.lan_wan": "forwarding", "firewall.lan_wan.src": "lan",
            "firewall.lan_wan.dest": "wan",
            "firewall.docker_wan": "forwarding", "firewall.docker_wan.src": "docker",
            "firewall.docker_wan.dest": "wan", "firewall.docker_wan.enabled": "1",
            "firewall.guest_wan": "forwarding", "firewall.guest_wan.src": "guest",
            "firewall.guest_wan.dest": "wan", "firewall.guest_wan.enabled": "0",
            "firewall.lan_iot": "forwarding", "firewall.lan_iot.src": "lan",
            "firewall.lan_iot.dest": "iot", "firewall.lan_iot.enabled": "1",
            "firewall.passwall_lan": "rule", "firewall.passwall_lan.src": "lan",
        }
        self.config.write_text(json.dumps(self.original))

    def run_script(self, mode, success=True):
        result = subprocess.run(["sh", str(self.script), mode], env=self.env,
                                text=True, capture_output=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_legacy_marker_is_on_and_off_apply_is_selective(self):
        self.assertEqual(self.run_script("state").stdout.strip(), "on")
        self.base.joinpath("enabled").write_text("0\n")
        self.run_script("apply")
        calls = self.commands()
        self.assertFalse(any("add" in call or "replace" in call for call in calls))
        flushed = [call[-1] for call in calls if call[:4] == ["ip", "-4", "route", "flush"]]
        self.assertEqual(flushed, ["51820", "51821"])
        deletes = [call for call in calls if call[:4] == ["ip", "-4", "rule", "del"]]
        self.assertEqual(len(deletes), 6)
        self.assertTrue(all("iif" in call and "pref" in call for call in deletes))
        self.assertFalse(any(call[0] == "uci" for call in calls))

    def test_on_off_restores_only_forwarding_flags_and_resnapshots(self):
        self.base.joinpath("enabled").write_text("0\n")
        self.run_script("on")
        active = json.loads(self.config.read_text())
        self.assertEqual(active["firewall.lan_wan.enabled"], "0")
        self.assertEqual(active["firewall.docker_wan.enabled"], "0")
        self.assertEqual(active["firewall.@defaults[0].flow_offloading"], "0")
        self.run_script("off")
        restored = json.loads(self.config.read_text())
        self.assertNotIn("firewall.lan_wan.enabled", restored)
        self.assertEqual(restored["firewall.docker_wan.enabled"], "1")
        self.assertEqual(restored["firewall.guest_wan.enabled"], "0")
        self.assertEqual(restored["firewall.lan_iot.enabled"], "1")
        self.assertEqual(restored["firewall.passwall_lan.src"], "lan")
        self.assertEqual(restored["firewall.@defaults[0].flow_offloading"], "0")
        # A deliberate user change while off becomes the next baseline.
        restored["firewall.docker_wan.enabled"] = "0"
        self.config.write_text(json.dumps(restored))
        self.run_script("enable")
        self.run_script("disable")
        self.assertEqual(json.loads(self.config.read_text())["firewall.docker_wan.enabled"], "0")
        self.assertEqual(self.run_script("state").stdout.strip(), "off")

    def test_legacy_first_off_uses_original_forwarding_flags_only(self):
        backup = self.root / "backup"
        backup.mkdir()
        self.base.joinpath("backup").write_text(str(backup))
        old = self.root / "old-firewall"
        old.write_text(json.dumps(self.original))
        with tarfile.open(backup / "restore.tar.gz", "w:gz") as archive:
            archive.add(old, arcname="etc/config/firewall")
        current = dict(self.original)
        current["firewall.lan_wan.enabled"] = "0"
        current["firewall.docker_wan.enabled"] = "0"
        current["firewall.passwall_lan.src"] = "wireguard"
        self.config.write_text(json.dumps(current))
        self.run_script("off")
        restored = json.loads(self.config.read_text())
        self.assertNotIn("firewall.lan_wan.enabled", restored)
        self.assertEqual(restored["firewall.docker_wan.enabled"], "1")
        self.assertEqual(restored["firewall.passwall_lan.src"], "wireguard")

    def test_duplicate_zone_pair_fails_before_enabling_or_changing_firewall(self):
        self.base.joinpath("enabled").write_text("0\n")
        current = dict(self.original)
        current.update({"firewall.duplicate": "forwarding", "firewall.duplicate.src": "lan",
                        "firewall.duplicate.dest": "wan"})
        self.config.write_text(json.dumps(current))
        result = self.run_script("on", success=False)
        self.assertIn("Duplicate lan -> wan", result.stderr)
        self.assertEqual(self.base.joinpath("enabled").read_text(), "0\n")
        self.assertEqual(json.loads(self.config.read_text()), current)


if __name__ == "__main__":
    unittest.main()
