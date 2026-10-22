#!/usr/bin/env bash
set -euo pipefail
# Preserve suites, components, signing settings, and third-party repositories.
sudo python3 - "${SETUP_APT_MIRROR:-https://mirrors.aliyun.com/ubuntu}" <<'PYCONFIG'
from pathlib import Path
import re, shutil, sys
from urllib.parse import urlparse
mirror=sys.argv[1].rstrip('/')
url=urlparse(mirror)
if url.scheme not in {'http','https'} or not url.netloc or any(c.isspace() for c in mirror):
    raise SystemExit('APT_MIRROR must be an HTTP(S) URL without whitespace')
paths=[Path('/etc/apt/sources.list'), Path('/etc/apt/sources.list.d/ubuntu.sources')]
changes=[]
for path in paths:
    if path.exists():
        original=path.read_text()
        updated=re.sub(r'https?://(?:[a-z]{2}\.)?(?:archive|security)\.ubuntu\.com/ubuntu/?',mirror,original)
        if updated != original: changes.append((path,updated))
if not changes:
    raise SystemExit('No supported Ubuntu archive URLs found; no files changed')
for path,updated in changes:
    backup=path.with_name(path.name+'.setup-backup')
    if not backup.exists(): shutil.copy2(path,backup)
    path.write_text(updated)
PYCONFIG
sudo apt-get update
