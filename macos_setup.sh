#!/usr/bin/env bash

# Use zsh as default shell
zsh_path="$( command -v zsh )"
sudo chsh -s "$zsh_path" $USER
echo "default shell changed to $zsh_path"

# Fix git: error: unable to locate xcodebuild
sudo xcode-select --switch /Library/Developer/CommandLineTools/

# Generate locate database
sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.locate.plist

dir="$(dirname "$0")"

# setup zsh
$dir/zsh_setup.sh
