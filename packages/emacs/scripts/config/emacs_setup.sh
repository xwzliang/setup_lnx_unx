#!/usr/bin/env bash
set -euo pipefail

# GitHub authentication is required for the private knowledge repository.
knowledge_dir="$HOME/git/my_zettelkasten"
mkdir -p "$HOME/git"
if [[ ! -d "$knowledge_dir/.git" ]]; then
    git clone https://github.com/xwzliang/my_zettelkasten.git "$knowledge_dir"
fi
mkdir -p "$knowledge_dir/wiki" "$knowledge_dir/persp"

cd "$HOME/git/dot_emacs"
make
