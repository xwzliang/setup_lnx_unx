#!/usr/bin/env bash

npm_packages_to_install=(
    bash-language-server				# A language server for Bash
)

for npm_package in "${npm_packages_to_install[@]}"; do
    if ! npm -g ls $npm_package; then
        echo -e "${npm_package} not installed, will install it\n"
        npm install -g $npm_package
    else
        echo -e "${npm_package} already installed, will skip it"
    fi
done
