#!/usr/bin/env bash
set -euo pipefail
if [[ -z ${SETUP_REPO_ROOT:-} ]]; then
    setup_location=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    while [[ ! -d "$setup_location/setup_tool" ]]; do
        [[ "$setup_location" != / ]] || { echo "Cannot locate setup repository" >&2; exit 1; }
        setup_location=$(dirname "$setup_location")
    done
    SETUP_REPO_ROOT=$setup_location
fi
"${SETUP_PYTHON:-python3}" - "$SETUP_REPO_ROOT" <<'PYPROFILE'
import sys
sys.path.insert(0, sys.argv[1])
from setup_tool.catalog import load_catalog, detect_os
from setup_tool.cli import main
names = ['ack', 'anki', 'ansible', 'apt-file', 'arandr', 'aria2', 'aspell', 'at', 'autoconf', 'automake', 'bash', 'bash-completion', 'bats', 'bcmwl-kernel-source', 'caddy', 'cask', 'check', 'cheese', 'clang-format', 'cmake', 'coreutils', 'curl', 'db-browser-for-sqlite', 'default-jre', 'djvulibre-bin', 'docker', 'dos2unix', 'elinks', 'emacs', 'entr', 'expect', 'exuberant-ctags', 'feh', 'ffmpeg', 'findutils', 'firefox', 'fish', 'fzf', 'gawk', 'gcc', 'gdb', 'git', 'git-filter-repo', 'git-flow', 'glimpse', 'global', 'gnu-sed', 'gnu-tar', 'go', 'go-dep', 'gpick', 'graphviz', 'grep', 'hfsprogs', 'imagemagick', 'java', 'jq', 'karabiner-elements', 'leiningen', 'libbz2-dev', 'libsox-fmt-mp3', 'libsqlite3-dev', 'libtool', 'libtool-bin', 'libvterm', 'maven', 'mongodb', 'mosh', 'mpv', 'mysql', 'nautilus-admin', 'ncurses', 'net-tools', 'node', 'ocrmypdf', 'openjdk@8', 'openssh-server', 'p7zip', 'p7zip-full', 'pandoc', 'pdsh', 'picom', 'poppler', 'postgresql', 'privoxy', 'progress', 'proxychains', 'pyenv', 'python3', 'python3-lxml', 'python3-pip', 'qpdf', 'qutebrowser', 'rar', 'readline', 'rename', 'ripgrep', 'ruby-full', 'scala', 'scrot', 'shadowsocks-libev', 'shfmt', 'silver-searcher', 'slock', 'sox', 'sshfs', 'tiv', 'tmux', 'tree', 'vagrant', 'valgrind', 'vim', 'virtualbox', 'w3m', 'wget', 'xss-lock', 'xterm', 'youtube-dl', 'zathura', 'zsh']
items, target = load_catalog(), detect_os()
for name in names:
    if target not in items[name].get("install", {}):
        print(f"Skipping {name}: no managed method on {target}")
        continue
    status = main(["install", name, "--os", target, "--apply"])
    if status:
        raise SystemExit(status)
PYPROFILE
