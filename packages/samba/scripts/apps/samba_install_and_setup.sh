#!/usr/bin/env bash
set -euo pipefail
: "${SETUP_SMB_USER:?Pass --set SMB_USER=existing-local-user}"
: "${SETUP_SMB_PATH:?Pass --set SMB_PATH=/absolute/directory}"
id "$SETUP_SMB_USER" >/dev/null
[[ "$SETUP_SMB_PATH" == /* && -d "$SETUP_SMB_PATH" && "$SETUP_SMB_PATH" != *$'\n'* ]] || { echo 'SMB_PATH must be an existing absolute directory' >&2; exit 1; }
sudo python3 - "$SETUP_SMB_PATH" <<'PYCONFIG'
from pathlib import Path
import re, shutil, sys
path=Path('/etc/samba/smb.conf'); text=path.read_text()
block='[setup-share]\n    path = '+sys.argv[1]+'\n    read only = no\n    browsable = yes\n'
if re.search(r'^\[setup-share\]',text,re.M):
    if block not in text: raise SystemExit('Existing setup-share differs; reconcile it manually')
else:
    backup=path.with_name('smb.conf.setup-backup')
    if not backup.exists(): shutil.copy2(path,backup)
    path.write_text(text.rstrip()+'\n\n'+block)
PYCONFIG
sudo smbpasswd -a "$SETUP_SMB_USER"
sudo testparm -s >/dev/null
sudo systemctl restart smbd
