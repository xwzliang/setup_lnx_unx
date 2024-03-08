#!/usr/bin/env bash

command_exists() {
    command -v "$@" > /dev/null 2>&1
}

# Install homebrew
install_brew() {
    if ! command_exists brew; then
        echo -e "brew not installed, will install it\n"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
    fi
}

install_brew

# Install packages
brew install --cask jellyfin
brew install --cask nextcloud
brew install --cask docker

sudo docker run \
--init \
--sig-proxy=false \
--name nextcloud-aio-mastercontainer \
--restart always \
--publish 80:80 \
--publish 8080:8080 \
--publish 8443:8443 \
--volume nextcloud_aio_mastercontainer:/mnt/docker-aio-config \
--volume /var/run/docker.sock.raw:/var/run/docker.sock:ro \
nextcloud/all-in-one:latest
