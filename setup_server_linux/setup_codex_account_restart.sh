#!/usr/bin/env bash
set -euo pipefail

# Install a user systemd path/service pair that restarts Codex on account change.
# Run this as the same non-root Linux user that runs Codex.

usage() {
    echo "Usage: $0 [--no-linger]"
}

enable_linger=1
case "${1:-}" in
    "") ;;
    --no-linger) enable_linger=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

if [[ $(id -u) -eq 0 ]]; then
    echo "Refusing to infer a Codex user from root. Run as the non-root user that runs Codex." >&2
    exit 1
fi

target_user=$(id -un)
target_uid=$(id -u)
passwd_record=$(getent passwd "$target_user")
real_home=$(printf '%s\n' "$passwd_record" | cut -d: -f6)
real_home=$(realpath -e "$real_home")
codex_home=$(realpath -m "${CODEX_HOME:-$real_home/.codex}")
config_file="$codex_home/config.toml"
auth_file="$codex_home/auth.json"
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

echo "Codex runtime diagnosis"
echo "  user=$target_user uid=$target_uid HOME=$real_home CODEX_HOME=$codex_home"
echo "  config=$config_file auth=$auth_file"

[[ $HOME == "$real_home" ]] || { echo "HOME does not match the passwd database" >&2; exit 1; }
[[ -f $config_file && -f $auth_file ]] || { echo "config.toml or auth.json is missing" >&2; exit 1; }
[[ $(stat -c %u "$auth_file") == "$target_uid" ]] || { echo "auth.json has the wrong owner" >&2; exit 1; }
chmod 600 "$auth_file"

python3 - "$config_file" <<'PY'
import pathlib, sys, tomllib
path = pathlib.Path(sys.argv[1])
with path.open("rb") as stream:
    config = tomllib.load(stream)
if config.get("cli_auth_credentials_store") != "file":
    raise SystemExit('config.toml must contain top-level cli_auth_credentials_store = "file"')
print('  config authentication store=file')
PY

command -v codex >/dev/null || { echo "codex is not on PATH" >&2; exit 1; }
codex_command=$(command -v codex)
codex_executable=$(realpath -e "$codex_command")
release_root=""
case "$codex_executable" in
    "$codex_home"/packages/standalone/releases/*/bin/codex)
        release_root="$codex_home/packages/standalone/releases"
        ;;
esac
echo "  codex command=$codex_command executable=$codex_executable"
codex login status
echo "  pgrep diagnostic (processes are narrowed by UID and executable below):"
pgrep -af codex || true

if [[ "$real_home$codex_home$codex_command$codex_executable" =~ [[:space:]] ]]; then
    echo "Paths containing whitespace are not supported in generated systemd units" >&2
    exit 1
fi

override_found=0
for variable in OPENAI_API_KEY CODEX_ACCESS_TOKEN; do
    if [[ -n ${!variable:-} ]]; then
        echo "  WARNING: $variable is set in the installer environment"
        override_found=1
    else
        echo "  $variable is unset in the installer environment"
    fi
done
for pid_dir in /proc/[0-9]*; do
    [[ -r $pid_dir/status && -r $pid_dir/environ ]] || continue
    [[ $(awk '/^Uid:/{print $2}' "$pid_dir/status") == "$target_uid" ]] || continue
    process_executable=$(readlink -f "$pid_dir/exe" 2>/dev/null || true)
    process_is_codex=0
    if [[ $process_executable == "$codex_executable" ]]; then
        process_is_codex=1
    elif [[ -n $release_root && $process_executable == "$release_root"/* ]]; then
        relative_executable=${process_executable#"$release_root"/}
        release_version=${relative_executable%%/*}
        if [[ -n $release_version && ${relative_executable#*/} == bin/codex ]]; then
            process_is_codex=1
        fi
    fi
    (( process_is_codex )) || continue
    for variable in OPENAI_API_KEY CODEX_ACCESS_TOKEN; do
        if tr '\0' '\n' < "$pid_dir/environ" | cut -d= -f1 | grep -Fxq "$variable"; then
            echo "  WARNING: $variable is set for Codex pid ${pid_dir##*/}"
            override_found=1
        fi
    done
done
if (( override_found )); then
    echo "File authentication is overridden; remove the override before installing." >&2
    exit 1
fi

echo "  auth JSON structure (key names only):"
python3 - "$auth_file" <<'PY'
import json, pathlib, sys
document = json.loads(pathlib.Path(sys.argv[1]).read_text())
def walk(value, prefix="$", depth=0):
    if not isinstance(value, dict) or depth > 3:
        return
    for key, child in value.items():
        print(f"    {prefix}.{key}: {type(child).__name__}")
        walk(child, f"{prefix}.{key}", depth + 1)
walk(document)
PY

libexec_dir="$real_home/.local/libexec"
state_dir="$real_home/.local/state/codex-auth-account-monitor"
unit_dir="$real_home/.config/systemd/user"
detector="$libexec_dir/codex-auth-account-monitor"
state_file="$state_dir/identity.sha256"
mkdir -p "$libexec_dir" "$state_dir" "$unit_dir"
chmod 700 "$state_dir"
install -m 700 "$source_dir/codex_auth_account_monitor.py" "$detector"

release_arguments=()
if [[ -n $release_root ]]; then
    release_arguments=(--release-root "$release_root")
fi

python3 "$source_dir/test_codex_auth_account_monitor.py"

# Establish the baseline before systemd can trigger the service. This never kills
# a process because no previous identity hash exists on a fresh installation.
if [[ ! -e $state_file ]]; then
    "$detector" \
        --auth-file "$auth_file" \
        --state-file "$state_file" \
        --codex-exe "$codex_command" \
        "${release_arguments[@]}" \
        --uid "$target_uid"
fi

service_unit="$unit_dir/codex-auth-account-monitor.service"
path_unit="$unit_dir/codex-auth-account-monitor.path"
release_exec=""
if [[ -n $release_root ]]; then
    release_exec=" --release-root $release_root"
fi

cat > "$service_unit" <<EOF
[Unit]
Description=Terminate Codex sessions after a ChatGPT account identity change
ConditionPathIsRegular=$auth_file

[Service]
Type=oneshot
UMask=0077
ExecStart=$detector --auth-file $auth_file --state-file $state_file --codex-exe $codex_command$release_exec --uid $target_uid
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$state_dir $auth_file
EOF

# Watching the containing directory catches Cockpit's rename-based atomic replace.
cat > "$path_unit" <<EOF
[Unit]
Description=Watch the Codex credential directory for account changes

[Path]
PathChanged=$auth_file
PathChanged=$codex_home
Unit=codex-auth-account-monitor.service

[Install]
WantedBy=default.target
EOF
chmod 600 "$service_unit" "$path_unit"

systemctl --user daemon-reload
systemctl --user enable --now codex-auth-account-monitor.path

if (( enable_linger )); then
    linger=$(loginctl show-user "$target_user" -p Linger --value 2>/dev/null || true)
    if [[ $linger != yes ]]; then
        echo "Enabling systemd lingering for $target_user (sudo may prompt)..."
        sudo loginctl enable-linger "$target_user"
    fi
fi

systemctl --user is-enabled codex-auth-account-monitor.path
systemctl --user is-active codex-auth-account-monitor.path
systemctl --user show codex-auth-account-monitor.service -p Result --value
echo "Installation complete. The oneshot service is inactive between path events by design."
