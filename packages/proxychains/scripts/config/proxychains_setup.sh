#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname)" == Darwin ]]; then
    config="$(brew --prefix)/etc/proxychains.conf"
elif [[ -f /etc/proxychains4.conf ]]; then
    config=/etc/proxychains4.conf
else
    config=/etc/proxychains.conf
fi
sudo python3 - "$config" <<'PYCONFIG'
from pathlib import Path
import re, shutil, sys
path=Path(sys.argv[1]); original=path.read_text()
# Replace the default local SOCKS4 endpoint; preserve custom proxies and sections.
updated=re.sub(r'(?m)^socks4\s+127\.0\.0\.1\s+9050\s*$', 'socks5 127.0.0.1 1080', original)
if 'socks5 127.0.0.1 1080' not in updated:
    raise SystemExit('Custom proxy list found; configure its endpoint manually')
if original!=updated:
    backup=path.with_name(path.name+'.setup-backup')
    if not backup.exists(): shutil.copy2(path,backup)
    path.write_text(updated)
PYCONFIG
