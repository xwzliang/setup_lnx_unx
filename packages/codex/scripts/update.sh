#!/usr/bin/env bash
# Standalone Codex updater: https://learn.chatgpt.com/docs/cli
set -euo pipefail
if [[ $# -gt 0 ]]; then
    echo 'Usage: update.sh (updates an existing standalone Codex installation)' >&2
    exit 2
fi
codex_path=$(command -v codex) || { echo 'Codex is not on PATH; install it separately first.' >&2; exit 1; }
# Follow links without requiring GNU readlink (also works on macOS).
resolved=$codex_path
while [[ -L "$resolved" ]]; do
    target=$(readlink "$resolved")
    if [[ "$target" == /* ]]; then resolved=$target; else resolved="$(dirname "$resolved")/$target"; fi
done
case "$resolved" in
    */packages/standalone/*/bin/codex) ;;
    *) echo 'This updater requires a standalone Codex installation. For npm use: npm install -g @openai/codex@latest; for Homebrew use: brew upgrade --cask codex' >&2; exit 1 ;;
esac
command -v curl >/dev/null || { echo 'curl is required.' >&2; exit 1; }
"$codex_path" --version
installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl --fail --silent --show-error --location https://chatgpt.com/codex/install.sh --output "$installer"
sh "$installer"
"$codex_path" --version
echo 'Update complete. Restart running Codex sessions to use the new version.'
