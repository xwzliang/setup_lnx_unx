#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script only supports macOS." >&2
    exit 1
fi

DEFER_UNTIL="${SETUP_DEFER_UNTIL:-2099-01-01 00:00:00 +0000}"
WITH_SUDO=0

usage() {
    cat <<'EOF'
Usage: disable_update_notifications.sh [--with-sudo] [--defer-until DATE]

Suppresses macOS software update popup notification banners and clears the
System Settings attention badge for pending macOS updates.

Options:
  --with-sudo          Also disable system-wide background update checks and
                       downloads via sudo (softwareupdate --schedule off).
  --defer-until DATE   Timestamp passed to UserNotificationDate and
                       MajorOSUserNotificationDate (default: 2099-01-01 00:00:00 +0000).
  -h, --help           Show this help message.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-sudo)
            WITH_SUDO=1
            shift
            ;;
        --defer-until)
            [[ $# -ge 2 ]] || { echo "Missing value for --defer-until" >&2; exit 2; }
            DEFER_UNTIL="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

echo "Deferring macOS update notification dates until: $DEFER_UNTIL"
defaults write com.apple.SoftwareUpdate UserNotificationDate -date "$DEFER_UNTIL"
defaults write com.apple.SoftwareUpdate MajorOSUserNotificationDate -date "$DEFER_UNTIL"

SYS_PREFS_PLIST="$HOME/Library/Preferences/com.apple.systempreferences.plist"
if [[ -f "$SYS_PREFS_PLIST" ]] && command -v python3 >/dev/null 2>&1; then
    status=0
    updated_plist="$(defaults export "$SYS_PREFS_PLIST" - | python3 -c '
import plistlib, sys

data = plistlib.loads(sys.stdin.buffer.read())
attention = data.get("AttentionPrefBundleIDs")
if not isinstance(attention, dict):
    sys.exit(10)

targets = {
    "com.apple.FollowUpSettings.FollowUpSettingsExtension",
    "com.apple.preferences.softwareupdate",
    "com.apple.Software-Update-Settings.extension",
}
changed = False
for key in list(attention.keys()):
    if key in targets:
        del attention[key]
        changed = True

if not changed:
    sys.exit(10)

plistlib.dump(data, sys.stdout.buffer)
')" || status=$?
    if [[ $status -eq 0 && -n "$updated_plist" ]]; then
        printf '%s\n' "$updated_plist" | defaults import "$SYS_PREFS_PLIST" -
        echo "Cleared Software Update attention badge from System Settings preferences."
    elif [[ $status -ne 0 && $status -ne 10 ]]; then
        echo "Warning: unable to inspect $SYS_PREFS_PLIST (exit code $status)." >&2
    fi
fi

apply_system_softwareupdate_prefs() {
    local prefix=()
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
        prefix=(sudo)
    fi
    "${prefix[@]}" softwareupdate --schedule off >/dev/null
    "${prefix[@]}" defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled -bool false
    "${prefix[@]}" defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload -bool false
    echo "Disabled system-wide automatic update checking and background downloads."
}

if [[ ${EUID:-$(id -u)} -eq 0 ]] || sudo -n true 2>/dev/null || [[ $WITH_SUDO -eq 1 ]]; then
    apply_system_softwareupdate_prefs
else
    echo "Note: skipped system-wide /Library/Preferences/com.apple.SoftwareUpdate changes (sudo requires a password)."
    echo "To also stop background checks for future macOS versions, run:"
    echo "  sudo softwareupdate --schedule off"
    echo "  sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled -bool false"
    echo "  sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload -bool false"
fi

for proc in SoftwareUpdateNotificationManager NotificationCenter Dock; do
    killall "$proc" 2>/dev/null || true
done

echo "Done. Refreshed notification and Dock services."
