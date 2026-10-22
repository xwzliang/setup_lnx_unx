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
open -a Docker
open -a Jellyfin
for attempt in {1..30}; do
    docker info >/dev/null 2>&1 && break
    sleep 2
done
docker info >/dev/null
docker compose -f "$SETUP_REPO_ROOT/packages/nextcloud/scripts/macos/nextcloud/docker-compose.yml" up -d
docker compose -f "$SETUP_REPO_ROOT/packages/guacamole/scripts/macos/guacamole/docker-compose.yml" up -d
