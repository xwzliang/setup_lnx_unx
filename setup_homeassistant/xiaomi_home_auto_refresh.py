#!/usr/bin/env python3
"""Install and run an additions-only Xiaomi Home device-list refresh for HAOS."""

import argparse
from contextlib import contextmanager, suppress
import fcntl
import getpass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

NAME = "xiaomi_home_auto_refresh"
TOKEN_PATH = Path(".home-assistant") / "token"
FLOW = "/api/config/config_entries/options/flow"
OPTION_KEYS = {
    "integration_language", "update_user_info", "network_detect_config",
    "update_devices", "display_devices_changed_notify", "update_lan_ctrl_config",
    "action_debug", "hide_non_standard_entities", "display_binary_mode",
    "cover_dead_zone_width", "update_trans_rules",
}


class RefreshError(Exception):
    pass


def read_json(path):
    return json.loads(path.read_bytes())


def active_entry(config):
    entries = read_json(config / ".storage/core.config_entries")["data"]["entries"]
    active = [entry for entry in entries if entry["domain"] == "xiaomi_home" and not entry.get("disabled_by")]
    if len(active) != 1:
        raise RefreshError("Expected exactly one enabled Xiaomi Home integration.")
    entry = active[0]
    data = entry["data"]
    if data.get("devices_filter") or entry.get("options"):
        raise RefreshError("Customized device filters or entry options require a manual refresh.")
    uid, region = str(data["uid"]), data["cloud_server"]
    if not re.fullmatch(r"[0-9]+", uid) or not re.fullmatch(r"[a-z]+", region):
        raise RefreshError("Unexpected Xiaomi Home account identifier.")
    if not data.get("home_selected") or not data.get("ctrl_mode"):
        raise RefreshError("The Xiaomi Home entry has no selected home or control mode.")
    return entry


def cache_members(config, entry):
    data = entry["data"]
    path = config / ".storage/xiaomi_home/miot_devices" / f"{data['uid']}_{data['cloud_server']}.dict"
    blob = path.read_bytes()
    payload = blob[:-32]
    if hashlib.sha256(payload).digest() != blob[-32:]:
        raise RefreshError("The Xiaomi device cache failed its checksum.")
    cache = json.loads(payload)
    if not isinstance(cache, dict) or not cache:
        raise RefreshError("Unexpected Xiaomi device cache structure.")
    return set(cache)


class HA:
    def __init__(self, token):
        self.token = token
        self.deadline = time.monotonic() + 48

    def request(self, method, path, data=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RefreshError("The Home Assistant flow exceeded its time budget.")
        conn = http.client.HTTPConnection("127.0.0.1", 8123, timeout=min(18, remaining))
        try:
            conn.request(method, path, json.dumps(data) if data is not None else None,
                         {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
            response = conn.getresponse()
            if response.status in (401, 403):
                raise RefreshError("Home Assistant rejected the token. Use an administrator token.")
            if response.status != 200:
                raise RefreshError(f"Home Assistant options flow returned HTTP {response.status}.")
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise RefreshError("Home Assistant options response exceeded the expected size.")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise RefreshError("Unexpected Home Assistant options response.")
            return result
        finally:
            conn.close()


def fields(result, step, required, optional=()):
    errors = result.get("errors")
    # Xiaomi Home v0.4.7 reports a blank base error on the initial home selection.
    if step == "homes_select" and errors == {"base": ""}:
        errors = {}
    if result.get("type") != "form" or result.get("step_id") != step or errors:
        raise RefreshError(f"Expected the Xiaomi Home {step} form. Review the options flow manually.")
    schema = result.get("data_schema")
    if not isinstance(schema, list) or any(not isinstance(f, dict) or "name" not in f for f in schema):
        raise RefreshError("Unexpected Xiaomi Home form schema.")
    seen = {f["name"]: f for f in schema}
    if not set(required) <= seen.keys() or seen.keys() - set(required) - set(optional) or len(seen) != len(schema):
        raise RefreshError(f"Unexpected fields on the Xiaomi Home {step} form.")
    return seen


def defaults(schema):
    values = {}
    for name, field in schema.items():
        if "default" in field:
            values[name] = field["default"]
        elif field.get("required"):
            raise RefreshError(f"Xiaomi Home supplied no default for {name}.")
    return values


def change_count(preview, key):
    value = preview.get("description_placeholders", {}).get(key)
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise RefreshError("The Xiaomi Home preview has no recognized device counts.")
    return int(value)


def refresh(config, api, *, apply):
    entry = active_entry(config)
    data = entry["data"]
    existing = cache_members(config, entry)
    initial = api.request("POST", FLOW, {"handler": entry["entry_id"]})
    flow_id = initial.get("flow_id", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", flow_id):
        raise RefreshError("Home Assistant did not return a valid options-flow ID.")
    resource = f"{FLOW}/{flow_id}"
    submitting = False
    try:
        options = defaults(fields(initial, "config_options", OPTION_KEYS - {"cover_dead_zone_width"},
                                  {"cover_dead_zone_width"}))
        for name in ("update_user_info", "network_detect_config", "update_lan_ctrl_config", "update_trans_rules"):
            if options.get(name) is not False:
                raise RefreshError("Xiaomi Home unexpectedly selected a second configuration operation.")
        if options.get("update_devices") is not False:
            raise RefreshError("Unexpected default for the Xiaomi device-list refresh.")
        options["update_devices"] = True
        homes = api.request("POST", resource, options)
        selection = defaults(fields(homes, "homes_select", {"home_infos", "devices_filter", "ctrl_mode"}))
        expected_homes = set(data["home_selected"])
        selected_homes = selection.get("home_infos")
        if (not isinstance(selected_homes, list) or set(selected_homes) != expected_homes
                or selection.get("ctrl_mode") != data["ctrl_mode"] or selection.get("devices_filter") is not False):
            raise RefreshError("The options flow would change the selected homes, control mode, or device filters.")
        summary = api.request("POST", resource, selection)
        fields(summary, "config_confirm", {"confirm"})
        added = change_count(summary, "devices_add")
        removed = change_count(summary, "devices_remove")
        if removed:
            return f"Skipped: Xiaomi proposes {added} additions and {removed} removals. Review the device list manually."
        if not added:
            return "No new devices to import."
        if not apply:
            return f"Preview: would import {added} devices with zero removals."
        if active_entry(config) != entry or cache_members(config, entry) != existing:
            raise RefreshError("Xiaomi Home changed during the preview. Device sync was skipped.")
        # A commit timeout may still mean the integration accepted the change.
        submitting = True
        try:
            result = api.request("POST", resource, {"confirm": True})
        except (OSError, http.client.HTTPException, ValueError, RefreshError):
            raise RefreshError("The final refresh response was lost or rejected. Check Xiaomi Home before retrying.") from None
        if result.get("type") != "create_entry":
            submitting = False
            raise RefreshError("Home Assistant did not confirm the device-list refresh.")
        return f"Xiaomi Home accepted the import of {added} devices with zero removals."
    finally:
        if not submitting:
            with suppress(RefreshError, OSError, http.client.HTTPException, ValueError):
                api.request("DELETE", resource)


def automation_yaml(config):
    data = active_entry(config)["data"]
    language = data["integration_language"]
    if not re.fullmatch(r"[A-Za-z-]+", language):
        raise RefreshError("Unexpected Xiaomi Home language.")
    i18n = config / "custom_components/xiaomi_home/miot/i18n" / f"{language}.json"
    heading = read_json(i18n)["miot"]["client"]["device_list_add"]
    labels = [line.strip() for line in heading.splitlines() if "{count}" in line and "{message}" not in line]
    if len(labels) != 1:
        raise RefreshError("Could not identify the new-device notification heading.")
    escaped = re.escape(labels[0]).replace(re.escape("{count}"), r"[1-9][0-9]*")
    pattern = json.dumps(r"(?m)^" + escaped + r"[ \t]*$", ensure_ascii=False)
    ident = f"xiaomi_home-{data['uid']}-{data['cloud_server']}-dev_list_changed"
    return f"""# Installed by xiaomi_home_auto_refresh.py. Keep this file in Home Assistant packages.
shell_command:
  xiaomi_home_auto_refresh_devices: 'python3 /config/{NAME}/refresh.py run --apply'

automation:
  - id: xiaomi_home_refresh_added_devices
    alias: Xiaomi Home · Import newly discovered devices
    mode: single
    max_exceeded: silent
    variables:
      addition_pattern: {pattern}
    triggers:
      - trigger: persistent_notification
        notification_id: {json.dumps(ident)}
        update_type:
          - added
          - updated
    conditions:
      - condition: template
        value_template: "{{{{ trigger.notification.message | regex_search(addition_pattern) }}}}"
    actions:
      - action: shell_command.xiaomi_home_auto_refresh_devices
        response_variable: refresh_result
      - if:
          - condition: template
            value_template: "{{{{ refresh_result.returncode != 0 }}}}"
        then:
          - action: system_log.write
            data:
              level: warning
              logger: xiaomi_home_auto_refresh
              message: "{{{{ refresh_result.stderr | trim }}}}"
"""


def install_file(path, payload, mode):
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise RefreshError(f"Existing file differs. Review it before replacing {path.name}.")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent) as temp:
        os.fchmod(temp.fileno(), mode)
        temp.write(payload)
        temp.flush()
        os.fsync(temp.fileno())
        os.link(temp.name, path)


def read_token(path):
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RefreshError("Create the token file as a regular file with mode 0600.")
    token = path.read_text().strip()
    if not token or any(char.isspace() for char in token):
        raise RefreshError("The token file must contain one administrator access token.")
    return token


def install(config, token_stdin):
    if not re.search(r"(?m)^ +packages: *!include_dir_named +packages\s*(?:#.*)?$",
                     (config / "configuration.yaml").read_text()):
        raise RefreshError("Home Assistant must already include packages with !include_dir_named packages.")
    automation = automation_yaml(config)
    package_dir = config / "packages"
    runtime = config / NAME
    token = config / TOKEN_PATH
    for directory in (package_dir, runtime, token.parent):
        if directory.is_symlink() or directory.exists() and not directory.is_dir():
            raise RefreshError(f"Unexpected installation directory: {directory.name}.")
    runtime.mkdir(mode=0o700, exist_ok=True)
    if not token.exists() and not token.is_symlink():
        if not token_stdin and not sys.stdin.isatty():
            raise RefreshError("Use an interactive terminal or supply the token with --token-stdin.")
        value = sys.stdin.read().strip() if token_stdin else getpass.getpass("Home Assistant administrator token: ").strip()
        if not value or any(char.isspace() for char in value):
            raise RefreshError("Enter one Home Assistant administrator access token.")
        token.parent.mkdir(mode=0o700, exist_ok=True)
        install_file(token, (value + "\n").encode(), 0o600)
    read_token(token)
    package_dir.mkdir(exist_ok=True)
    install_file(runtime / "refresh.py", Path(__file__).read_bytes(), 0o600)
    install_file(package_dir / (NAME + ".yaml"), automation.encode(), 0o640)
    print("Installed. Check Home Assistant configuration, then reload Shell Command and Automations.")


@contextmanager
def one_at_a_time(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RefreshError("A Xiaomi Home refresh is already running.") from None
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=Path("/config"))
    group = parser.add_subparsers(dest="command")
    setup = group.add_parser("install", help="Install in an existing Home Assistant configuration directory")
    setup.add_argument("--token-stdin", action="store_true", help="Read the token from stdin instead of prompting")
    run = group.add_parser("run", help="Preview or apply an additions-only refresh")
    run.add_argument("--apply", action="store_true", help="Confirm the flow when it lists zero removals")
    args = parser.parse_args()
    config = args.config_dir.resolve()
    try:
        if args.command == "run":
            with one_at_a_time(config / NAME / "refresh.lock"):
                print(refresh(config, HA(read_token(config / TOKEN_PATH)), apply=args.apply))
        else:
            install(config, getattr(args, "token_stdin", False))
    except RefreshError as exc:
        sys.exit(str(exc))
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError):
        sys.exit("Xiaomi Home refresh could not read its config or complete the options flow. Check it manually.")


if __name__ == "__main__":
    main()
