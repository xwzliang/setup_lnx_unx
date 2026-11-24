#!/usr/bin/env bash
set -euo pipefail
[[ $# == 0 ]] || { echo 'Usage: update.sh' >&2; exit 2; }
command -v agy >/dev/null || { echo 'agy is not installed or not on PATH' >&2; exit 1; }
export AGY_CLI_DISABLE_AUTO_UPDATE=true
agy --version
agy update
agy --version
printf '%s\n' 'Restart running agy sessions to use the updated version.'
