#!/usr/bin/env bash

# install-iina-plugins.sh
#
# Reads GitHub repo URLs from:
#   ./iina-plugin-repos.txt
#
# One repo URL per line.
# Empty lines and lines starting with # are ignored.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_LIST="$SCRIPT_DIR/iina-plugin-repos.txt"

PLUGIN_DIR="$HOME/Library/Application Support/com.colliderli.iina/plugins"
IINA_BUNDLE_ID="com.colliderli.iina"

if [ ! -f "$REPO_LIST" ]; then
    echo "ERROR: Repo list not found:"
    echo "  $REPO_LIST"
    exit 1
fi

install_plugin() {
    local repo_url="$1"
    local tmp_dir
    tmp_dir="$(mktemp -d)"

    cleanup() {
        rm -rf "$tmp_dir"
    }
    trap cleanup RETURN

    echo
    echo "=================================================="
    echo "Processing: $repo_url"
    echo "=================================================="

    echo "Cloning temporarily to inspect plugin identifier..."
    if ! git clone --depth=1 "$repo_url" "$tmp_dir/repo"; then
        echo "ERROR: git clone failed, skipping."
        return 1
    fi

    local info_json
    info_json="$(find "$tmp_dir/repo" -iname "Info.json" | head -n 1)"

    if [ -z "$info_json" ]; then
        echo "ERROR: Could not find Info.json, skipping."
        return 1
    fi

    local identifier
    identifier="$(python3 - "$info_json" <<'PY'
import json
import sys

path = sys.argv[1]

try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(data.get("identifier", ""))
except Exception:
    print("")
PY
)"

    if [ -z "$identifier" ]; then
        echo "ERROR: No identifier found in Info.json, skipping."
        return 1
    fi

    local plugin_name="${identifier}.iinaplugin"
    local target_path="$PLUGIN_DIR/$plugin_name"

    echo "Identifier: $identifier"
    echo "Target: $target_path"

    mkdir -p "$PLUGIN_DIR"

    if [ -d "$target_path" ]; then
        echo "Plugin folder already exists, skipping installation:"
        echo "  $target_path"

        echo "Ensuring plugin is enabled..."
        defaults write "$IINA_BUNDLE_ID" "PluginEnabled.${identifier}" -bool true

        return 2
    fi

    if [ -e "$target_path" ]; then
        echo "ERROR: Target path exists but is not a directory, skipping:"
        echo "  $target_path"
        return 1
    fi

    cp -R "$tmp_dir/repo" "$target_path"

    echo "Installed: $plugin_name"

    echo "Enabling plugin..."
    defaults write "$IINA_BUNDLE_ID" "PluginEnabled.${identifier}" -bool true

    return 0
}

installed=0
skipped=0
failed=0

while IFS= read -r line || [ -n "$line" ]; do
    repo_url="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

    [ -z "$repo_url" ] && continue
    [[ "$repo_url" == \#* ]] && continue

    install_plugin "$repo_url"
    result=$?

    if [ "$result" -eq 0 ]; then
        installed=$((installed + 1))
    elif [ "$result" -eq 2 ]; then
        skipped=$((skipped + 1))
    else
        failed=$((failed + 1))
    fi
done < "$REPO_LIST"

echo
echo "=================================================="
echo "Done."
echo "Installed: $installed"
echo "Skipped existing: $skipped"
echo "Failed: $failed"
echo "Restart IINA to load installed plugins."
echo "=================================================="