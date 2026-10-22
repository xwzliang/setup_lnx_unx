#!/usr/bin/env bash

mkdir -p "$HOME/Downloads/bin"
cd "$HOME/Downloads/bin"

# curl -O https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
curl -O https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb

sudo apt install ./google-chrome-stable_current_amd64.deb
