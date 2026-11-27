import hashlib
import importlib.util
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "packages/xiaomi-home-auto-refresh/scripts/xiaomi_home_auto_refresh.py"
spec = importlib.util.spec_from_file_location("xiaomi_refresh", path)
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def form(step, values, counts=None):
    return {
        "type": "form", "flow_id": "options-test", "step_id": step, "errors": {},
        "data_schema": [
            {"name": name, "default": value, "required": True} for name, value in values.items()
        ],
        "description_placeholders": counts,
    }


class FakeHA:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return {} if method == "DELETE" else next(self.responses)


class XiaomiRefreshTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.entry = {
            "entry_id": "xiaomi-entry", "domain": "xiaomi_home", "options": {},
            "data": {"uid": "1234", "cloud_server": "cn", "ctrl_mode": "auto",
                     "home_selected": {"home-id": {}}, "devices_filter": {}, "integration_language": "zh-Hans"},
        }
        cache_dir = self.path / ".storage/xiaomi_home/miot_devices"
        cache_dir.mkdir(parents=True)
        self.registry = self.path / ".storage/core.config_entries"
        self.write_entry()
        data = b'{"existing-device": {"online": true}}'
        self.cache_path = cache_dir / "1234_cn.dict"
        self.cache_path.write_bytes(data + hashlib.sha256(data).digest())
        self.home_options = {"home_infos": ["home-id"], "ctrl_mode": "auto", "devices_filter": False}
        self.options = {key: False for key in refresh.OPTION_KEYS}
        self.options.update(integration_language="zh-Hans", display_devices_changed_notify=["add", "del", "offline"],
                            display_binary_mode=["binary_sensor"], cover_dead_zone_width=0)

    def write_entry(self):
        self.registry.write_text(json.dumps({"data": {"entries": [self.entry]}}))

    def api(self, additions=2, removals=0, *, home_options=None, options=None):
        return FakeHA([
            form("config_options", self.options if options is None else options),
            form("homes_select", self.home_options if home_options is None else home_options),
            form("config_confirm", {"confirm": False}, {"devices_add": str(additions), "devices_remove": removals}),
            {"type": "create_entry"},
        ])

    def test_only_additions_are_confirmed_and_defaults_are_preserved(self):
        api = self.api()
        self.assertIn("accepted the import of 2", refresh.refresh(self.path, api, apply=True))
        self.assertEqual(api.calls[0], ("POST", refresh.FLOW, {"handler": "xiaomi-entry"}))
        self.assertEqual(api.calls[1][2], {**self.options, "update_devices": True})
        self.assertEqual(api.calls[2][2], self.home_options)
        self.assertEqual(api.calls[3], ("POST", refresh.FLOW + "/options-test", {"confirm": True}))

    def test_preview_no_change_and_removal_always_abort_without_commit(self):
        for added, removed, apply in [(2, 0, False), (0, 0, True), (2, 1, True), (0, 1, True)]:
            with self.subTest(added=added, removed=removed, apply=apply):
                api = self.api(added, removed)
                refresh.refresh(self.path, api, apply=apply)
                self.assertTrue(all(call[2] != {"confirm": True} for call in api.calls))
                self.assertEqual(api.calls[-1][0], "DELETE")

    def test_missing_option_and_changed_home_abort(self):
        without_refresh_option = {k:v for k,v in self.options.items() if k != "update_devices"}
        for api in (self.api(options=without_refresh_option),
                    self.api(home_options={**self.home_options, "home_infos": ["another-home"]})):
            with self.assertRaises(refresh.RefreshError):
                refresh.refresh(self.path, api, apply=True)
            self.assertEqual(api.calls[-1][0], "DELETE")

    def test_custom_filters_fail_before_making_a_request(self):
        self.entry["data"]["devices_filter"] = {"exclude": ["device"]}
        self.write_entry()
        api = self.api()
        with self.assertRaisesRegex(refresh.RefreshError, "filters"):
            refresh.refresh(self.path, api, apply=True)
        self.assertEqual(api.calls, [])

    def test_concurrent_membership_change_aborts(self):
        api = self.api()
        with patch.object(refresh, "cache_members", side_effect=[{"existing"}, {"existing", "added"}]):
            with self.assertRaisesRegex(refresh.RefreshError, "changed during"):
                refresh.refresh(self.path, api, apply=True)
        self.assertEqual(api.calls[-1][0], "DELETE")

    def test_install_is_idempotent_and_targets_only_addition_notices(self):
        i18n = self.path / "custom_components/xiaomi_home/miot/i18n/zh-Hans.json"
        i18n.parent.mkdir(parents=True)
        i18n.write_text(json.dumps({"miot": {"client": {"device_list_add": "\n**{count} 个新增设备**: \n{message}"}}}))
        config = "homeassistant:\n  packages: !include_dir_named packages\n"
        (self.path / "configuration.yaml").write_text(config)
        with patch("sys.stdin") as stdin:
            stdin.read.return_value = "fixture-token"
            refresh.install(self.path, token_stdin=True)
        refresh.install(self.path, token_stdin=False)
        raw = (self.path / "packages/xiaomi_home_auto_refresh.yaml").read_text()
        pattern = json.loads(re.search(r"^      addition_pattern: (.+)$", raw, re.M)[1])
        self.assertRegex("\n**12 个新增设备**: \n- device", pattern)
        self.assertNotRegex("\n**3 个设备离线**: \n- device", pattern)
        self.assertIn("xiaomi_home-1234-cn-dev_list_changed", raw)
        self.assertNotIn("fixture-token", raw)
        self.assertEqual((self.path / refresh.NAME / "token").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.path / "configuration.yaml").read_text(), config)
