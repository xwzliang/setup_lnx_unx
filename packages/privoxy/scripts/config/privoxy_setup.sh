#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname)" == Darwin ]]; then
    config="$(brew --prefix)/etc/privoxy/config"
else
    config=/etc/privoxy/config
fi
line='forward-socks5 / 127.0.0.1:1080 .'
if ! sudo grep -Fqx "$line" "$config"; then
    printf '%s\n' "$line" | sudo tee -a "$config" >/dev/null
fi
if [[ "$(uname)" == Darwin ]]; then brew services start privoxy; else sudo systemctl restart privoxy; fi
