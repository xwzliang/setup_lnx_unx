#!/usr/bin/env bash
set -euo pipefail
: "${SETUP_ZOTERO_PROFILE:?Pass --set ZOTERO_PROFILE=/absolute/path/to/your/profile}"
: "${SETUP_ATTACHMENT_DIR:?Pass --set ATTACHMENT_DIR=/absolute/path/to/attachments}"
python3 - "$SETUP_ZOTERO_PROFILE" "$SETUP_ATTACHMENT_DIR" <<'PYCONFIG'
from pathlib import Path
import json, sys
profile,attachments=map(Path,sys.argv[1:])
if not profile.is_absolute() or not profile.is_dir() or not attachments.is_absolute():
    raise SystemExit('Provide an existing absolute profile directory and an absolute attachment directory')
path=profile/'user.js'
content='// setup_lnx_unx: attachment base directory\nuser_pref("extensions.zotero.baseAttachmentPath", '+json.dumps(str(attachments))+');\n'
if path.is_symlink() or (path.exists() and path.read_text()!=content):
    raise SystemExit('Existing user.js differs; merge settings manually. Nothing overwritten.')
attachments.mkdir(parents=True,exist_ok=True)
path.write_text(content)
PYCONFIG
echo 'Attachment path configured. Restart Zotero; install compatible extensions through Zotero itself.'
