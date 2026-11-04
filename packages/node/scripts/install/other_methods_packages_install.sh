#!/usr/bin/env bash
set -eo pipefail
# Keep the historical version explicit and overridable; no eval or personal aliases.
nvm_version=${SETUP_NVM_VERSION:-v0.35.3}
node_version=${SETUP_NODE_VERSION:-node}
[[ "$nvm_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'NVM_VERSION must be a version tag such as v0.35.3' >&2; exit 1; }
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
    installer=$(mktemp)
    trap 'rm -f "$installer"' EXIT
    curl -fL "https://raw.githubusercontent.com/nvm-sh/nvm/$nvm_version/install.sh" -o "$installer"
    bash "$installer"
fi
# nvm is a shell function and must be loaded in this process before installing Node.
source "$NVM_DIR/nvm.sh"
nvm install "$node_version"
