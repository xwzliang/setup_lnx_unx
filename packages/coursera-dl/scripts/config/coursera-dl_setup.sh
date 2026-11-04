#!/usr/bin/env bash
set -euo pipefail
: "${SETUP_COURSERA_USER:?Pass --set COURSERA_USER=your-login}"
python3 - "$SETUP_COURSERA_USER" <<'PYCONFIG'
from pathlib import Path
import getpass, json, os, re, sys
path=Path.home()/'.netrc'
if path.is_symlink(): raise SystemExit('Refusing to overwrite a .netrc symlink')
text=path.read_text() if path.exists() else ''
if re.search(r'\bmachine\s+coursera-dl\b',text):
    raise SystemExit('A coursera-dl entry exists; update it manually rather than replacing credentials')
password=getpass.getpass('Coursera password: ')
entry='machine coursera-dl login '+json.dumps(sys.argv[1])+' password '+json.dumps(password)+'\n'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
with os.fdopen(fd,'w') as file: file.write(('\n' if text and not text.endswith('\n') else '')+entry)
path.chmod(0o600)
PYCONFIG
