#!/usr/bin/env bash

# Use linuxbrew or homebrew to install packages on Linux or MacOS

brew_packages_to_install=(
    minikube				# a tool that runs a single-node Kubernetes cluster in a virtual machine on your personal computer
)

for app in "${brew_packages_to_install[@]}"; do
    if brew ls --versions ${app} > /dev/null; then
        echo -e "${app} already installed, will skip it"
    else
        if brew info ${app} > /dev/null 2>&1 ; then
            echo -e "${app} not installed, will install it\n"
            HOMEBREW_NO_AUTO_UPDATE=1 brew install ${app}
        else
            echo "${app} is not available in homebrew."
        fi
    fi
done

