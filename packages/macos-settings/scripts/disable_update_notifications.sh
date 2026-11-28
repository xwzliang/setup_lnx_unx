#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script only supports macOS." >&2
    exit 1
fi

DEFER_UNTIL="${SETUP_DEFER_UNTIL:-2099-01-01 00:00:00 +0000}"
WITH_SUDO=0
RESTORE=0

usage() {
    cat <<'EOF'
Usage: disable_update_notifications.sh [--with-sudo] [--defer-until DATE] [--restore]

Suppresses macOS software update popup notification banners (including
insufficient-space auto-download alerts), disables SoftwareUpdateNotification in
Notification Center preferences, and clears the System Settings attention badge.

Options:
  --with-sudo          Also disable system-wide background update checks and
                       downloads via sudo (softwareupdate --schedule off).
  --defer-until DATE   Timestamp passed to UserNotificationDate and
                       MajorOSUserNotificationDate (default: 2099-01-01 00:00:00 +0000).
  --restore            Re-enable SoftwareUpdateNotificationManager, restore
                       Notification Center permissions, and clear deferred dates.
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
        --restore)
            RESTORE=1
            shift
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

update_ncprefs() {
    local mode="$1"
    command -v python3 >/dev/null 2>&1 || return 0
    local status=0
    local updated_ncprefs
    updated_ncprefs="$(defaults export com.apple.ncprefs - | python3 -c '
import plistlib, sys

mode = sys.argv[1]
data = plistlib.loads(sys.stdin.buffer.read())
apps = data.get("apps")
if not isinstance(apps, list):
    sys.exit(10)

target_id = "_SYSTEM_CENTER_:com.apple.SoftwareUpdateNotification"
changed = False
for app in apps:
    if not isinstance(app, dict) or app.get("bundle-id") != target_id:
        continue
    flags = int(app.get("flags", 0))
    auth = app.get("auth")
    if mode == "disable":
        # Clear Notification Center enabled/alert/banner/lockscreen/sound/badge bits and deny auth.
        new_flags = flags & ~((1 << 25) | (1 << 24) | (1 << 4) | (1 << 3) | (1 << 2) | (1 << 1) | (1 << 0))
        new_auth = 0
    else:
        new_flags = (flags & ~(1 << 3)) | (1 << 25) | (1 << 24) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0)
        new_auth = 7
    if flags != new_flags or auth != new_auth:
        app["flags"] = new_flags
        app["auth"] = new_auth
        changed = True

if not changed:
    sys.exit(10)

plistlib.dump(data, sys.stdout.buffer)
' "$mode")" || status=$?
    if [[ $status -eq 0 && -n "$updated_ncprefs" ]]; then
        printf '%s\n' "$updated_ncprefs" | defaults import com.apple.ncprefs -
        if [[ "$mode" == "disable" ]]; then
            echo "Disabled _SYSTEM_CENTER_:com.apple.SoftwareUpdateNotification in Notification Center."
        else
            echo "Restored _SYSTEM_CENTER_:com.apple.SoftwareUpdateNotification in Notification Center."
        fi
    elif [[ $status -ne 0 && $status -ne 10 ]]; then
        echo "Warning: unable to update com.apple.ncprefs (exit code $status)." >&2
    fi
}

USER_UID="$(id -u)"
LAUNCH_AGENT_LABEL="com.apple.SoftwareUpdateNotificationManager"
LAUNCH_AGENT_PLIST="/System/Library/LaunchAgents/${LAUNCH_AGENT_LABEL}.plist"
LAUNCH_TARGET="gui/${USER_UID}/${LAUNCH_AGENT_LABEL}"

if [[ $RESTORE -eq 1 ]]; then
    defaults delete com.apple.SoftwareUpdate UserNotificationDate 2>/dev/null || true
    defaults delete com.apple.SoftwareUpdate MajorOSUserNotificationDate 2>/dev/null || true
    update_ncprefs restore
    if command -v launchctl >/dev/null 2>&1; then
        launchctl enable "$LAUNCH_TARGET" 2>/dev/null || true
        if [[ -f "$LAUNCH_AGENT_PLIST" ]]; then
            launchctl bootstrap "gui/${USER_UID}" "$LAUNCH_AGENT_PLIST" 2>/dev/null || true
        fi
    fi
    for proc in usernoted NotificationCenter Dock; do
        killall "$proc" 2>/dev/null || true
    done
    echo "Restored macOS software update notification defaults and agent."
    exit 0
fi

echo "Deferring macOS update notification dates until: $DEFER_UNTIL"
defaults write com.apple.SoftwareUpdate UserNotificationDate -date "$DEFER_UNTIL"
defaults write com.apple.SoftwareUpdate MajorOSUserNotificationDate -date "$DEFER_UNTIL"

update_ncprefs disable

if command -v launchctl >/dev/null 2>&1; then
    if launchctl disable "$LAUNCH_TARGET" 2>/dev/null; then
        echo "Disabled launchd agent for future logins: $LAUNCH_TARGET"
    else
        echo "Warning: unable to disable $LAUNCH_TARGET via launchctl." >&2
    fi
    launchctl bootout "$LAUNCH_TARGET" 2>/dev/null || true
fi

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
    echo "To also stop background update downloads (e.g. insufficient-space checks), run:"
    echo "  sudo softwareupdate --schedule off"
    echo "  sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled -bool false"
    echo "  sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload -bool false"
fi

pkill -KILL -f "/SoftwareUpdateNotificationManager.app/Contents/MacOS/SoftwareUpdateNotificationManager" 2>/dev/null || true
for proc in usernoted NotificationCenter Dock; do
    killall "$proc" 2>/dev/null || true
done

echo "Done. Refreshed notification and Dock services."
