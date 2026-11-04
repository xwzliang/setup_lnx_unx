#!/usr/bin/env bash
set -euo pipefail
# Fetch Oh My Zsh without invoking its interactive installer or replacing .zshrc.
if [[ ! -d "$HOME/.oh-my-zsh" ]]; then
    git clone https://github.com/ohmyzsh/ohmyzsh.git "$HOME/.oh-my-zsh"
fi
plugin_dir="$HOME/.oh-my-zsh/custom/plugins/zsh-autosuggestions"
if [[ ! -d "$plugin_dir" ]]; then
    git clone https://github.com/zsh-users/zsh-autosuggestions "$plugin_dir"
fi
touch "$HOME/.zshrc" "$HOME/.zshenv"
if ! grep -Fq 'oh-my-zsh.sh' "$HOME/.zshrc"; then
    cat >> "$HOME/.zshrc" <<'CONFIG'

# setup_lnx_unx: Oh My Zsh
export ZSH="$HOME/.oh-my-zsh"
plugins+=(zsh-autosuggestions)
source "$ZSH/oh-my-zsh.sh"
CONFIG
fi
for alias_file in .zsh_aliases .all_sh_aliases; do
    printf -v line '[[ ! -f "$HOME/%s" ]] || source "$HOME/%s"' "$alias_file" "$alias_file"
    grep -Fqx "$line" "$HOME/.zshrc" || printf '%s\n' "$line" >> "$HOME/.zshrc"
done
line='[[ ! -f "$HOME/.all_sh_env" ]] || source "$HOME/.all_sh_env"'
grep -Fqx "$line" "$HOME/.zshenv" || printf '%s\n' "$line" >> "$HOME/.zshenv"
echo 'Zsh configured. Start zsh to use it; change your login shell separately if desired.'
