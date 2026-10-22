#!/usr/bin/env bash

nix_packages_to_install=(
    # fish				# fish installed by nix not working correctly with utf-8 chars
)

command_exists() {
    command -v "$@" > /dev/null 2>&1
}

for nix_package in "${nix_packages_to_install[@]}"; do
    if ! command_exists $nix_package; then
        echo -e "${nix_package} not installed, will install it\n"
        nix-env --install $nix_package
    else
        echo -e "${nix_package} already installed, will skip it"
    fi
done
