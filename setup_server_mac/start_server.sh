#!/usr/bin/env bash

open -a Docker
open_app Jellyfin

cd ~/git/setup_lnx_unx/setup_server_mac

sleep 10

cd nextcloud/
docker-compose up -d

cd ../guacamole
docker-compose up -d
