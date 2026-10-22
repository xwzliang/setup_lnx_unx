#!/usr/bin/env bash
set -euo pipefail
: "${SETUP_FSTAB_FILE:?Pass --set FSTAB_FILE=/absolute/path/to/reviewed/entries}"
sudo python3 - "$SETUP_FSTAB_FILE" <<'PYCONFIG'
from pathlib import Path
import shutil, subprocess, sys
source=Path(sys.argv[1])
if not source.is_absolute() or not source.is_file(): raise SystemExit('FSTAB_FILE must be an existing absolute file')
rows=[line for line in source.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
parsed=[line.split() for line in rows]
if not parsed or any(len(row)!=6 or not row[1].startswith('/') or row[1]=='/' for row in parsed):
    raise SystemExit('Supply six-field fstab entries with absolute, non-root mount points')
if len({row[1] for row in parsed}) != len(parsed): raise SystemExit('Duplicate mount points in input')
path=Path('/etc/fstab'); original=path.read_text()
existing=[line.split() for line in original.splitlines() if line.strip() and not line.lstrip().startswith('#')]
for row in parsed:
    if any(len(old)>1 and old[1]==row[1] and old!=row for old in existing):
        raise SystemExit('Conflicting existing mount: '+row[1])
new=[line for line,row in zip(rows,parsed) if row not in existing]
if new:
    backup=path.with_name('fstab.setup-backup')
    if not backup.exists(): shutil.copy2(path,backup)
    path.write_text(original.rstrip()+'\n'+'\n'.join(new)+'\n')
for row in parsed:
    Path(row[1]).mkdir(parents=True,exist_ok=True)
    subprocess.run(['mount',row[1]],check=True)
PYCONFIG
