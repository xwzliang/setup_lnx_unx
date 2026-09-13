#!/bin/sh
# Install daily Codex Luna runs at 05:00, 10:05, 15:10 Singapore time.
# Usage: ./setup_codex_hi_cron.sh
# Run as your normal user after `codex login`, not with sudo.
# Requires codex-cli, crontab, and an active cron service.
# A minute-level shell check avoids nonportable CRON_TZ behavior and DST issues.
# Only the three matching minutes invoke the model; setup makes no model calls.
set -eu
umask 077

die() { printf '%s\n' "$*" >&2; exit 1; }
quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

case "${1-}" in
  -h|--help)
    sed -n '2,8s/^# \{0,1\}//p' "$0"
    exit 0 ;;
  '') ;;
  *) die "Usage: $0 [--help]" ;;
esac
case "$(uname -s)" in Darwin|Linux) ;; *) die 'Only macOS and Linux are supported.' ;; esac
: "${HOME:?HOME must be set}"
codex_bin=$(command -v codex) || die 'Install codex-cli and add codex to PATH first.'
command -v crontab >/dev/null 2>&1 || die 'Install cron/crontab and enable the cron service first.'
case "$codex_bin" in /*) ;; *) die 'codex must resolve to an absolute executable path.' ;; esac

# Reject characters that crontab itself interprets even inside shell quotes.
case "$HOME$codex_bin" in
  *'%'*|*'
'*) die 'HOME and the Codex executable path must not contain percent signs or newlines.' ;;
esac
codex_help=$("$codex_bin" exec --help)
for flag in --ignore-user-config --ephemeral --skip-git-repo-check --output-last-message; do
  printf '%s\n' "$codex_help" | grep -q -- "$flag" || die "Update codex-cli: missing $flag."
done
login_status=$("$codex_bin" login status 2>&1) || die 'Run codex login with your ChatGPT account first.'
case "$login_status" in
  *'Logged in using ChatGPT'*) ;;
  *) die 'ChatGPT login is required for this quota-window use case. Run codex login first.' ;;
esac

install_dir=$HOME/.local/share/codex-hi-cron
runner=$install_dir/run.sh
mkdir -p "$install_dir/work"
temp_dir=$(mktemp -d "$install_dir/setup.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT
trap 'exit 1' HUP INT TERM

# Fail closed on permission errors, rather than overwrite an unreadable crontab.
if LC_ALL=C crontab -l > "$temp_dir/before" 2> "$temp_dir/error"; then
  :
elif grep -qi 'no crontab for' "$temp_dir/error"; then
  : > "$temp_dir/before"
else
  cat "$temp_dir/error" >&2
  die 'Unable to read existing crontab; nothing installed.'
fi

{
  printf '#!/bin/sh\nset -eu\numask 077\n'
  printf 'task_dir=%s\n' "$(quote "$install_dir")"
  printf 'codex_bin=%s\n' "$(quote "$codex_bin")"
  printf 'export PATH=%s\n' "$(quote "$(dirname "$codex_bin"):/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")"
  cat <<'RUNNER'
# POSIX TZ syntax: UTC-8 means UTC+08:00, without requiring zoneinfo files.
export TZ=UTC-8
slot=$(date '+%Y-%m-%d_%H:%M')
case "$slot" in *_05:00|*_10:05|*_15:10) ;; *) exit 0 ;; esac

# Prevent overlapping runs and duplicate calls in the same scheduled minute.
if ! mkdir "$task_dir/run.lock" 2>/dev/null; then exit 0; fi
trap 'rmdir "$task_dir/run.lock"' EXIT
trap 'exit 1' HUP INT TERM
previous_slot=''
if [ -f "$task_dir/last-slot" ]; then
  IFS= read -r previous_slot < "$task_dir/last-slot" || :
fi
[ "$slot" != "$previous_slot" ] || exit 0
printf '%s\n' "$slot" > "$task_dir/last-slot"
exec > "$task_dir/latest.log" 2>&1
printf 'Scheduled run: %s Singapore time\n' "$slot"
status=0
"$codex_bin" exec \
  --ignore-user-config --ephemeral --skip-git-repo-check \
  --cd "$task_dir/work" --sandbox read-only --color never \
  --model gpt-5.6-luna \
  -c 'model_reasoning_effort="low"' \
  -c 'project_doc_max_bytes=0' \
  --output-last-message "$task_dir/last-message.txt" \
  'Reply only hi. Do not use tools.' < /dev/null || status=$?
printf '\nExit status: %s\n' "$status"
exit "$status"
RUNNER
} > "$temp_dir/run.sh"
/bin/sh -n "$temp_dir/run.sh"
chmod 700 "$temp_dir/run.sh"

# Replace our managed block; also migrate the three original local jobs.
awk -v legacy="$HOME/.local/bin/codex-hi-cron.sh" '
  $0 == "# BEGIN codex-hi-cron" { managed=1; next }
  $0 == "# END codex-hi-cron" { managed=0; next }
  managed { next }
  $0 == "0 5 * * * /bin/sh " legacy { next }
  $0 == "5 10 * * * /bin/sh " legacy { next }
  $0 == "10 15 * * * /bin/sh " legacy { next }
  { print }
  END { if (managed) exit 1 }
' "$temp_dir/before" > "$temp_dir/after" || die 'Unclosed managed cron block; repair it before retrying.'
{
  printf '# BEGIN codex-hi-cron\n'
  printf '# Shell checks Singapore time; Codex runs only at 05:00, 10:05, 15:10 daily.\n'
  printf '* * * * * /bin/sh %s\n' "$(quote "$runner")"
  printf '# END codex-hi-cron\n'
} >> "$temp_dir/after"

# Retain the first pre-install crontab for reference (do not blindly restore later).
if [ ! -f "$install_dir/crontab.before-first-install" ]; then
  cp "$temp_dir/before" "$install_dir/crontab.before-first-install"
fi
mv "$temp_dir/run.sh" "$runner"
crontab "$temp_dir/after"
crontab -l > "$temp_dir/installed"
cmp -s "$temp_dir/after" "$temp_dir/installed" || die 'Installed crontab differs; inspect crontab -l.'
printf '%s\n' \
  'Installed: daily 05:00, 10:05, 15:10 Singapore time (independent of system timezone).' \
  'Model: gpt-5.6-luna; reasoning: low; response: hi. No model call made during setup.' \
  "Runner: $runner" \
  "Latest log: $install_dir/latest.log" \
  'Keep the machine awake, online, and cron running. Missed runs are not replayed.' \
  'Quota refresh timing and exact token consumption are not guaranteed.' \
  'To uninstall: use crontab -e and remove the BEGIN/END codex-hi-cron block.' \
  "If a killed process leaves a stale lock, remove $install_dir/run.lock after confirming no run is active."
