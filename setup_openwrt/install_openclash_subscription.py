#!/usr/bin/env python3
"""Convert named .env subscriptions and install them through SSH (Python 3.9+)."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from install_openclash_killswitch import Installer

HERE = Path(__file__).resolve().parent
TEMPLATE = "https://raw.githubusercontent.com/xwzliang/mysubconverter/refs/heads/master/myconfig/wgetcloud.ini"
IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")


def read_env(path):
    """Read literal KEY=value entries, never execute or interpolate shell code."""
    result = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) or key in result:
            raise ValueError(f"Invalid or duplicate .env key on line {number}")
        if value.startswith(("'", '\"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed .env quote on line {number}")
            value = value[1:-1]
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"Control character on .env line {number}")
        result[key] = value
    return result


def http_url(value, label):
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in ("http", "https") and parsed.hostname and not any(c.isspace() for c in value)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be an HTTP(S) URL")
    return value


def settings(env, names, all_names, require_urls=True):
    identifiers = env.get("SUBSCRIPTIONS", "").split()
    if not identifiers or any(not IDENT.fullmatch(n) for n in identifiers):
        raise ValueError("SUBSCRIPTIONS must contain unique identifiers: letters, digits and underscores")
    canonical = {name.casefold(): name for name in identifiers}
    if len(canonical) != len(identifiers):
        raise ValueError("SUBSCRIPTIONS identifiers must be unique ignoring case")
    active = canonical.get(env.get("ACTIVE_SUBSCRIPTION", "").casefold())
    if active is None:
        raise ValueError("ACTIVE_SUBSCRIPTION / --switch must name an entry in SUBSCRIPTIONS (case-insensitive)")
    selected = []
    for name in identifiers if all_names else names:
        resolved = canonical.get(name.casefold())
        if resolved is None:
            raise ValueError("Unknown subscription identifier; choose from: " + ", ".join(identifiers))
        if resolved not in selected:
            selected.append(resolved)
    configs = {}
    subscriptions = {}
    for name in identifiers:
        prefix = f"SUB_{name}_"
        filename = env.get(prefix + "CONFIG", name)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", filename) or filename in configs.values():
            raise ValueError("Subscription CONFIG names must be unique safe filenames, without .yaml")
        configs[name] = filename
        subscriptions[name] = (filename, http_url(env.get(prefix + "URL", ""), prefix + "URL") if require_urls else "",
                               http_url(env.get(prefix + "TEMPLATE", env.get("TEMPLATE_URL", TEMPLATE)), "Template") if require_urls else "")
    return [(name, *subscriptions[name]) for name in selected], active, configs[active]


# This worker is a file on the router, so OpenClash restart cleanup and loss of
# the initiating SSH connection cannot terminate the transaction.
PREAMBLE = r"""#!/bin/sh
set -e
umask 077
cd "$1"
exec >worker.log 2>&1
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }
phase() { printf '%s\n' "$1" >phase; log "Stage: $1"; }
validate_core() {
    phase "core-validation-$2"
    log "Core version: $(/etc/openclash/clash -v 2>&1)"
    log "Checking config: $1; detailed output: validation-$2.log"
    if /etc/openclash/clash -t -d /etc/openclash -f "$1" >"validation-$2.log" 2>&1; then
        cat "validation-$2.log"
        log "Core validation passed: $2"
    else
        validation_rc=$?
        cat "validation-$2.log"
        log "ERROR: Core validation failed: $2 (exit $validation_rc)"
        return "$validation_rc"
    fi
}
log "Subscription worker started; private directory: $PWD"
exec 9>/tmp/lock/setup-openclash-subscription.lock
flock -n 9 || { echo busy >result; exit 1; }
exec 8>/tmp/lock/openclash_subs.lock
flock -n 8 || { echo busy >result; exit 1; }
mutated=0
restart_needed=0
fetch_dir=
restart_core() {
    log "Restarting OpenClash; detailed output: restart.log"
    /etc/init.d/openclash restart >restart.log 2>&1 8>&- 9>&- &
    restart_pid=$!
    n=0
    while kill -0 "$restart_pid" 2>/dev/null; do
        n=$((n+1))
        if [ "$n" -ge 120 ]; then
            kill "$restart_pid" 2>/dev/null || :
            cat restart.log
            log "ERROR: OpenClash restart timed out"
            return 1
        fi
        sleep 1
    done
    if wait "$restart_pid"; then
        log "OpenClash restart command completed"
    else
        restart_rc=$?
        cat restart.log
        log "ERROR: OpenClash restart failed (exit $restart_rc)"
        return "$restart_rc"
    fi
}
rollback() {
    rc=$?
    log "ERROR: Worker exited with code $rc during $(cat phase 2>/dev/null || echo preflight)"
    trap - EXIT HUP INT TERM
    if [ -n "$fetch_dir" ]; then rm -rf "$fetch_dir"; fi
    if [ "$mutated" = 1 ]; then
        log "Restoring previous settings and config files from $PWD/backup"
        uci revert openclash || :
        cp backup/openclash /etc/config/openclash
        while IFS= read -r file; do
            if [ -f "backup$file" ]; then
                cp "backup$file" "$file.restore"
                mv "$file.restore" "$file"
            else
                rm -f "$file"
            fi
        done <manifest
        if [ "$restart_needed" = 1 ]; then restart_core || :; fi
        log "Previous settings and config files restored"
        echo rolled-back >result
    else
        log "Stopped before installation; existing settings and configs unchanged"
        echo failed-before-install >result
    fi
    exit "$rc"
}
trap rollback EXIT
trap 'exit 1' HUP INT TERM
for cmd in ruby flock uci; do command -v "$cmd" >/dev/null; done
test -x /etc/openclash/clash
test -z "$(uci changes openclash)" || { echo 'Uncommitted OpenClash UCI changes'; exit 1; }
. /lib/functions.sh
find_section() {
    config_get entry_name "$1" name
    if [ "$entry_name" = "$wanted" ]; then
        test -z "$matched_section" || { echo 'Duplicate subscription name'; exit 1; }
        matched_section=$1
    fi
}
config_load openclash
mkdir -p candidates backup
: >manifest
: >updates
"""


def worker(entries, active, active_config, converter_port, check_only=False, switch_only=False, user_agents=None):
    q = shlex.quote
    user_agents = user_agents or {}
    parts = [PREAMBLE]
    if not switch_only:
        parts.append("command -v curl >/dev/null\n")
    for name, config, url, template in entries:
        if switch_only:
            parts.append(f"""
phase validating-{name}
test -s /etc/openclash/config/{config}.yaml || {{ echo 'Saved config is missing; use --switch with --update first'; exit 1; }}
validate_core /etc/openclash/config/{config}.yaml {name}
""")
            continue
        parts.append(f"""
phase converting-{name}
wanted={q(config)}
matched_section=
config_foreach find_section config_subscribe
if [ -z "$matched_section" ]; then
    matched_section=setup_sub_{name}
    if uci -q get "openclash.$matched_section" >/dev/null; then echo 'Section name collision'; exit 1; fi
    printf 'set openclash.%s=config_subscribe\n' "$matched_section" >>updates
fi
printf %s {q(url)} >source-url
printf %s {q(template)} >template-url
phase fetching-{name}
# The default Docker deployment mounts /etc/openclash/config at /data.
# Keep the temporary raw subscription private and remove it after conversion.
fetch_dir=$(mktemp -d /etc/openclash/config/.subscription-fetch.XXXXXX)
ruby -e 'puts "url = " + File.read(ARGV[0]).dump' source-url >fetch.curl
status=000
for user_agent in {" ".join(q(agent) for agent in dict.fromkeys([user_agents.get(name, ""), "Clash", "Quantumultx"]) if agent)}; do
    status=$(curl --noproxy '*' -sS -L --connect-timeout 10 --max-time 60 \
        -K fetch.curl -A "$user_agent" -o "$fetch_dir/source.yaml" \
        -w '%{{http_code}}') || status=000
    echo "Source fetch ($user_agent): HTTP $status"
    if [ "$status" = 200 ] && [ -s "$fetch_dir/source.yaml" ]; then break; fi
done
[ "$status" = 200 ] && [ -s "$fetch_dir/source.yaml" ] || exit 1
printf %s "/data/${{fetch_dir##*/}}/source.yaml" >converter-source
phase converting-{name}
status=$(curl --noproxy '*' -sS --connect-timeout 15 --max-time 180 -G \
    --data-urlencode url@converter-source --data-urlencode config@template-url \
    --data target=clash --data new_name=true --data emoji=false --data list=false \
    --data sort=false --data scv=false --data append_type=false --data fdn=true \
    -o candidates/{config}.yaml -w '%{{http_code}}' \
    http://127.0.0.1:{converter_port}/sub) || exit 1
log "Conversion HTTP $status; output: candidates/{config}.yaml ($(wc -c <candidates/{config}.yaml) bytes)"
if [ "$status" != 200 ]; then log "ERROR: Conversion failed; response retained in candidates/{config}.yaml"; exit 1; fi
phase yaml-validation-{name}
rm -rf "$fetch_dir"
fetch_dir=
ruby -ryaml -e 'c=YAML.load_file(ARGV[0]); abort "Invalid subscription" unless c.is_a?(Hash) && c["proxies"].is_a?(Array) && !c["proxies"].empty? && c["proxy-groups"].is_a?(Array) && c["rules"].is_a?(Array)' candidates/{config}.yaml
validate_core "$PWD/candidates/{config}.yaml" {name}
""")
        values = {"name": config, "enabled": "1", "address": url, "sub_convert": "1",
                  "convert_address": f"http://127.0.0.1:{converter_port}/sub", "template": "0",
                  "custom_template_url": template, "emoji": "false", "udp": "false",
                  "skip_cert_verify": "false", "sort": "false", "node_type": "false", "rule_provider": "false"}
        for key, value in values.items():
            # Quote once for UCI syntax, then again for the shell printf argument.
            parts.append(f"printf 'set openclash.%s.{key}=%s\\n' \"$matched_section\" {q(q(value))} >>updates\n")
        parts.append(f"printf '%s\\n' /etc/openclash/config/{config}.yaml /etc/openclash/backup/{config}.yaml >>manifest\n")
    parts.append("rm -f source-url template-url fetch.curl converter-source\n")
    if check_only:
        parts.append("trap - EXIT HUP INT TERM\necho validated >result\nexit 0\n")
        return "".join(parts)
    if any(name == active for name, *_ in entries):
        parts.append(f"printf '%s\\n' {q('set openclash.config.config_path=' + q('/etc/openclash/config/' + active_config + '.yaml'))} 'set openclash.config.enable=1' >>updates\nrestart_needed=1\n")
    else:
        # Refreshing the current file also needs a restart.
        parts.append('current=$(uci -q get openclash.config.config_path || :)\nif grep -Fx "$current" manifest >/dev/null; then restart_needed=1; fi\n')
    # Inactive saved subscriptions may supply native fallback nodes too.
    parts.append("if test -f /etc/openclash/split-dns/settings.yaml && grep -q provider_failover /etc/openclash/split-dns/settings.yaml; then restart_needed=1; fi\n")
    parts.append(r"""
phase installing
log "Backing up settings and configs to $PWD/backup"
cp /etc/config/openclash backup/openclash
while IFS= read -r file; do
    mkdir -p "backup${file%/*}"
    if [ -f "$file" ]; then cp -p "$file" "backup$file"; fi
done <manifest
mutated=1
mkdir -p /etc/openclash/backup
while IFS= read -r file; do
    cp "candidates/${file##*/}" "$file.new"
    mv "$file.new" "$file"
done <manifest
uci batch <updates
uci commit openclash
if [ "$restart_needed" = 1 ]; then
    phase restarting
    restart_core
    raw=$(uci -q get openclash.config.config_path)
    runtime="/etc/openclash/${raw##*/}"
    ready=0
    for n in $(seq 1 45); do
        for pid in $(pidof clash || :); do
            if tr '\000' '\n' <"/proc/$pid/cmdline" | grep -Fx "$runtime" >/dev/null; then ready=1; fi
        done
        [ "$ready" = 0 ] || break
        sleep 2
    done
    [ "$ready" = 1 ]
fi
trap - EXIT HUP INT TERM
log "Installation and activation checks completed successfully"
echo installed >result
""")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=HERE / ".env", help="Default: .env next to this script")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--name", nargs="+", help="One or more identifiers from SUBSCRIPTIONS (case-insensitive)")
    choice.add_argument("--all", action="store_true", help="Update every configured identifier")
    choice.add_argument("--switch", metavar="IDENTIFIER", help="Activate its saved config without fetching or converting (case-insensitive identifier)")
    parser.add_argument("--update", action="store_true", help="With --switch, fetch and convert before activation")
    parser.add_argument("--router", help="Override ROUTER (default 192.168.5.1)")
    parser.add_argument("--port", type=int, help="Override SSH_PORT (default 22)")
    parser.add_argument("--check-only", action="store_true", help="Validate the requested operation without changing OpenClash")
    args = parser.parse_args()
    if args.update and not args.switch:
        parser.error("--update requires --switch IDENTIFIER")
    env = read_env(args.env)
    switch_only = bool(args.switch and not args.update)
    if args.switch:
        # Override this invocation only; do not rewrite the user's .env.
        env["ACTIVE_SUBSCRIPTION"] = args.switch
    entries, active, active_config = settings(
        env, [args.switch] if args.switch else args.name or [], args.all,
        require_urls=not switch_only)
    args.router = args.router or env.get("ROUTER", "192.168.5.1")
    args.port = args.port or int(env.get("SSH_PORT", "22"))
    converter_port = int(env.get("SUBCONVERTER_PORT", "15051"))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.router):
        raise ValueError("Invalid router address or SSH alias")
    if not all(1 <= p <= 65535 for p in (args.port, converter_port)):
        raise ValueError("Ports must be between 1 and 65535")
    user_agents = {name: env.get(f"SUB_{name}_USER_AGENT", "") for name, *_ in entries}
    payload = worker(entries, active, active_config, converter_port, args.check_only, switch_only, user_agents)
    with tempfile.TemporaryDirectory(prefix="openclash-sub-") as tmp:
        remote = Installer(args, Path(tmp) / "ssh")
        try:
            remote.connect()
            stage = remote.remote("umask 077; mktemp -d /root/openclash-subscription.XXXXXX")
            if not re.fullmatch(r"/root/openclash-subscription\.[A-Za-z0-9]+", stage):
                raise RuntimeError("Unexpected staging path")
            remote.remote(f"umask 077; cat > {stage}/run.sh", payload)
            remote.remote(f"nohup sh {stage}/run.sh {stage} >/dev/null 2>&1 </dev/null &")
            print(("Switching saved config: " if switch_only else "Converting: ") + ", ".join(e[0] for e in entries), flush=True)
            print("Private router logs and backups: " + stage, flush=True)
            deadline = time.monotonic() + 360 * len(entries) + 360
            last_phase = None
            while time.monotonic() < deadline:
                result = remote.remote(f"cat {stage}/result 2>/dev/null || true")
                if result:
                    if result not in ("validated", "installed"):
                        raise RuntimeError(f"Subscription update: {result}. Private details: {stage}/worker.log")
                    print(result.capitalize() + ": " + ", ".join(e[0] for e in entries))
                    return
                phase = remote.remote(f"cat {stage}/phase 2>/dev/null || true")
                if phase and phase != last_phase:
                    print(phase, flush=True)
                    last_phase = phase
                time.sleep(3)
            raise RuntimeError("Timed out waiting; router worker continues. Inspect " + stage + "/result")
        finally:
            subprocess.run(remote.ssh + ["-O", "exit", remote.target], capture_output=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(1)
