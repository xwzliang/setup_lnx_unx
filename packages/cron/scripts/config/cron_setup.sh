#!/usr/bin/env bash
set -euo pipefail
# Preserve the existing crontab; do not disable system updates.
command -v dropboxd >/dev/null || { echo 'Install/configure Dropbox first' >&2; exit 1; }
existing=$(crontab -l 2>/dev/null || true)
entry="@reboot $(command -v dropboxd) start"
if ! printf '%s\n' "$existing" | grep -Fqx "$entry"; then
    printf '%s\n%s\n' "$existing" "$entry" | crontab -
fi
