"""Run the actual DNS and provider hooks together through protection toggles."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SERVICE = "setup-failover/service/Antigravity"
SERVICE_RULE = f"DOMAIN,cloudcode-pa.googleapis.com,{SERVICE}"


class ProtectionProviderPreservation(unittest.TestCase):
    def test_protection_round_trip_keeps_provider_and_service_preferences(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            native_dir = root / "subscriptions"
            native_dir.mkdir()
            native = {
                "proxies": [{"name": "one-node", "type": "ss"}],
                "proxy-groups": [
                    {"name": "新加坡", "type": "url-test", "proxies": ["one-node"]},
                    {"name": "🚀 节点选择", "type": "select", "proxies": ["one-node", "DIRECT"]},
                    {"name": "🐟 漏网之鱼", "type": "select", "proxies": ["DIRECT", "🚀 节点选择"]},
                    {"name": "🎯 全球直连", "type": "select", "proxies": ["DIRECT", "🚀 节点选择"]},
                ],
                "dns": {
                    "enable": True,
                    "listen": "0.0.0.0:7874",
                    "enhanced-mode": "fake-ip",
                    "nameserver": ["223.5.5.5"],
                    "fallback": ["8.8.8.8"],
                    "nameserver-policy": {"+.domestic.example": "119.29.29.29"},
                    "fake-ip-filter": ["+.device.example"],
                },
                "rules": [
                    "DOMAIN,foreign.example,DIRECT",
                    "DOMAIN-SUFFIX,domestic.example,DIRECT",
                    "DOMAIN,protected.example,新加坡",
                    "IP-CIDR,17.0.0.0/8,DIRECT",
                    "GEOIP,CN,DIRECT",
                    "MATCH,🐟 漏网之鱼",
                ],
            }
            active = native_dir / "one.yaml"
            active.write_text(json.dumps(native, ensure_ascii=False))
            secondary = json.loads(json.dumps(native))
            secondary["proxies"][0]["name"] = "two-node"
            for group in secondary["proxy-groups"]:
                group["proxies"] = ["two-node" if name == "one-node" else name for name in group["proxies"]]
            (native_dir / "two.yaml").write_text(json.dumps(secondary, ensure_ascii=False))
            runtime = root / "runtime.yaml"
            runtime.write_text(json.dumps(native, ensure_ascii=False))

            # Keep the real transformation code and its relative import; redirect
            # only the router's native subscription directory into this fixture.
            code = (HERE / "split_dns.rb").read_text()
            self.assertEqual(code.count("'/etc/openclash/config'"), 1)
            script = root / "split_dns.rb"
            script.write_text(code.replace("'/etc/openclash/config'", json.dumps(str(native_dir))))
            shutil.copy2(HERE / "provider_failover.rb", root / "provider_failover.rb")
            settings = root / "settings.yaml"
            options = {
                "proxy_group": "新加坡",
                "provider_failover": {"ONE": "one", "TWO": "two"},
                "service_policies": [{
                    "name": "Antigravity", "region": "新加坡", "providers": ["TWO", "ONE"],
                    "matches": ["DOMAIN,cloudcode-pa.googleapis.com"],
                }],
            }

            def transform(protected):
                settings.write_text(json.dumps(dict(options, dns_protection=protected), ensure_ascii=False))
                result = subprocess.run(
                    ["ruby", str(script), str(runtime), str(settings), str(active)],
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = subprocess.check_output(
                    ["ruby", "-ryaml", "-rjson", "-e", "puts JSON.generate(YAML.load_file(ARGV[0]))", str(runtime)],
                    text=True, stderr=subprocess.PIPE, timeout=15,
                )
                config = json.loads(raw)
                groups = {group["name"]: group for group in config["proxy-groups"]}
                for name in ["新加坡", "🚀 节点选择", "🐟 漏网之鱼"]:
                    self.assertEqual(groups[name]["type"], "fallback")
                    self.assertEqual(groups[name]["proxies"], [f"setup-failover/ONE/{name}", f"setup-failover/TWO/{name}"])
                self.assertEqual(groups[SERVICE]["type"], "fallback")
                self.assertEqual(groups[SERVICE]["proxies"], ["setup-failover/TWO/新加坡", "setup-failover/ONE/新加坡"])
                self.assertEqual(groups["🎯 全球直连"]["proxies"], ["DIRECT"])
                self.assertEqual(config["rules"].count(SERVICE_RULE), 1)
                self.assertEqual(config["rules"][0], SERVICE_RULE)
                for rule in native["rules"][:3]:
                    self.assertIn(rule, config["rules"])
                self.assertEqual(config["x-setup-provider-failover"]["preferred"], "ONE")
                self.assertFalse(config["ipv6"])
                if protected:
                    self.assertEqual(config["dns"]["nameserver"], ["https://1.1.1.1/dns-query#新加坡"])
                    self.assertEqual(config["rules"][-1], "MATCH,新加坡")
                else:
                    self.assertEqual(config["dns"], native["dns"])
                    self.assertEqual(config["rules"], [SERVICE_RULE] + native["rules"])
                    self.assertNotIn("x-setup-split-dns-original", config)
                return config

            first_on = transform(True)
            self.assertEqual(transform(True), first_on, "repeated on must be idempotent")
            off = transform(False)
            self.assertEqual(transform(False), off, "repeated off must be idempotent")
            second_on = transform(True)
            self.assertEqual(transform(True), second_on, "on after off must also be idempotent")
            # The newly captured pre-policy snapshot can include the already
            # generated service rule; all effective routing/DNS must be identical.
            self.assertEqual(
                {key: value for key, value in first_on.items() if key != "x-setup-split-dns-original"},
                {key: value for key, value in second_on.items() if key != "x-setup-split-dns-original"},
            )


if __name__ == "__main__":
    unittest.main()
