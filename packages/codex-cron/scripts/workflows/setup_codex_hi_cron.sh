#!/bin/sh
# Install daily Codex Luna runs at 05:00, 10:05, 15:10 in the system timezone.
# Usage: ./setup_codex_hi_cron.sh
# Run as your normal user, not with sudo; sign in when prompted, then exit Codex.
# Installs missing codex-cli; requires crontab and an active cron service.
# Use Asia/Shanghai or Asia/Singapore for the intended UTC+8 schedule.
# If the system timezone changes, cron follows the new timezone.
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
command -v crontab >/dev/null 2>&1 || die 'Install cron/crontab and enable the cron service first.'
if ! codex_bin=$(command -v codex); then
  command -v curl >/dev/null 2>&1 || die 'Install curl before installing codex-cli.'
  printf '%s\n' 'Installing codex-cli...'
  # Let this script own the interactive sign-in step.
  (export CODEX_NON_INTERACTIVE=true; curl -fsSL https://chatgpt.com/codex/install.sh | sh)
  # The installer cannot update this parent shell's PATH.
  PATH="${CODEX_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
  export PATH
  codex_bin=$(command -v codex) || die 'Codex installation failed: codex is not on PATH.'
fi
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
login_status=$("$codex_bin" login status 2>&1) || login_status=''
case "$login_status" in
  *'Logged in using ChatGPT'*) ;;
  *)
    [ -t 0 ] && [ -t 1 ] || die 'Sign-in requires a terminal. Run this script interactively (ssh -t when using SSH).'
    printf '%s\n' 'Sign in with your ChatGPT account in Codex, then use /quit to continue cron setup.'
    "$codex_bin" || die 'Codex exited unsuccessfully; rerun setup to finish sign-in.'
    login_status=$("$codex_bin" login status 2>&1) || die 'Sign-in was not completed; rerun setup and sign in with ChatGPT.'
    ;;
esac
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
slot=$(date '+%Y-%m-%d_%H:%M')

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
printf 'Scheduled run: %s system timezone (%s)\n' "$slot" "$(date '+%Z %z')"
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
  printf '# Daily 05:00, 10:05, 15:10 in the system timezone; update if timezone changes.\n'
  printf '0 5 * * * /bin/sh %s\n' "$(quote "$runner")"
  printf '5 10 * * * /bin/sh %s\n' "$(quote "$runner")"
  printf '10 15 * * * /bin/sh %s\n' "$(quote "$runner")"
  printf '# END codex-hi-cron\n'
} >> "$temp_dir/after"

# Retain the first pre-install crontab for reference (do not blindly restore later).
if [ ! -f "$install_dir/crontab.before-first-install" ]; then
  cp "$temp_dir/before" "$install_dir/crontab.before-first-install"
fi
mv "$temp_dir/run.sh" "$runner"
if ! crontab "$temp_dir/after" 2> "$temp_dir/error"; then
  cat "$temp_dir/error" >&2
  if [ "$(uname -s)" = Darwin ] && grep -qi 'Operation not permitted' "$temp_dir/error"; then
    printf '%s\n' 'macOS: when running over SSH, enable System Settings > General > Sharing > Remote Login > Allow full disk access for remote users, then reconnect and rerun setup.' >&2
  fi
  die 'Unable to install crontab. Resolve cron permissions and rerun setup; the runner was saved.'
fi
crontab -l > "$temp_dir/installed"
cmp -s "$temp_dir/after" "$temp_dir/installed" || die 'Installed crontab differs; inspect crontab -l.'
printf '%s\n' \
  'Installed: daily 05:00, 10:05, 15:10 in the system timezone.' \
  'Use Asia/Shanghai or Asia/Singapore for UTC+8; update the schedules if the system timezone changes.' \
  'Model: gpt-5.6-luna; reasoning: low; response: hi. No model call made during setup.' \
  "Runner: $runner" \
  "Latest log: $install_dir/latest.log" \
  'Keep the machine awake, online, and cron running. Missed runs are not replayed.' \
  'Quota refresh timing and exact token consumption are not guaranteed.' \
  'To uninstall: use crontab -e and remove the BEGIN/END codex-hi-cron block.' \
  "If a killed process leaves a stale lock, remove $install_dir/run.lock after confirming no run is active."
