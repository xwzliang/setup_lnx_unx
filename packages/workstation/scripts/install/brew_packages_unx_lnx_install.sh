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
names = ['minikube', 'kubectl']
items, target = load_catalog(), detect_os()
for name in names:
    if target not in items[name].get("install", {}):
        print(f"Skipping {name}: no managed method on {target}")
        continue
    status = main(["install", name, "--os", target, "--apply"])
    if status:
        raise SystemExit(status)
PYPROFILE
