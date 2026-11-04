#!/usr/bin/env bash
set -euo pipefail
# Grant PDF read/write only, preserving the rest of the security policy.
sudo python3 - <<'PYCONFIG'
from pathlib import Path
import shutil, xml.etree.ElementTree as ET
paths=[p for p in (Path('/etc/ImageMagick-7/policy.xml'),Path('/etc/ImageMagick-6/policy.xml')) if p.exists()]
if len(paths)!=1: raise SystemExit('Expected exactly one installed ImageMagick policy; configure its PDF coder manually')
path=paths[0]; tree=ET.parse(path)
found=False
for node in tree.getroot().findall('policy'):
    if node.get('domain')=='coder' and node.get('pattern')=='PDF':
        node.set('rights','read|write'); found=True
if not found: ET.SubElement(tree.getroot(),'policy',domain='coder',rights='read|write',pattern='PDF')
backup=path.with_name('policy.xml.setup-backup')
if not backup.exists(): shutil.copy2(path,backup)
tree.write(path,encoding='unicode')
PYCONFIG
