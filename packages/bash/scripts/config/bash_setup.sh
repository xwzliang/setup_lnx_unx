#!/usr/bin/env bash
set -euo pipefail
touch "$HOME/.bashrc"
for alias_file in .bash_aliases .all_sh_aliases; do
    printf -v line '[ ! -f "$HOME/%s" ] || . "$HOME/%s"' "$alias_file" "$alias_file"
    grep -Fqx "$line" "$HOME/.bashrc" || printf '%s\n' "$line" >> "$HOME/.bashrc"
done
mkdir -p "$HOME/.local/share/setup_lnx_unx"
z_path="$HOME/.local/share/setup_lnx_unx/z.sh"
if [[ ! -f "$z_path" ]]; then
    curl -fL https://raw.githubusercontent.com/rupa/z/master/z.sh -o "$z_path"
fi
line='[ ! -f "$HOME/.local/share/setup_lnx_unx/z.sh" ] || . "$HOME/.local/share/setup_lnx_unx/z.sh"'
grep -Fqx "$line" "$HOME/.bashrc" || printf '%s\n' "$line" >> "$HOME/.bashrc"
