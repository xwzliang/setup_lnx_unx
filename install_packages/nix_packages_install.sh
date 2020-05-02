#!/usr/bin/env bash

nix_packages_to_install=(
    fish				# fish is a smart and user-friendly command line shell for Linux, macOS, and the rest of the family
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
