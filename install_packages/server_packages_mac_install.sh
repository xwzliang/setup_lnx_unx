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
