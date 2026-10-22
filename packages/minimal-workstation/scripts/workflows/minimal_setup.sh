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
for package in openssh-server tmux git git-lfs gcc sqlite3; do
    "$SETUP_REPO_ROOT/setup" install "$package" --apply
done
"$SETUP_REPO_ROOT/setup" install conda --apply
"$SETUP_REPO_ROOT/setup" configure directories --apply
"$SETUP_REPO_ROOT/setup" configure git --apply
git lfs install
