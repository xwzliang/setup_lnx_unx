#!/usr/bin/env bash

# Use zsh as default shell
if [[ ! "$SHELL" =~ zsh ]]; then
	zsh_path="$( command -v zsh )"
	sudo chsh -s "$zsh_path" $USER
	echo "default shell changed to $zsh_path"
fi

# Fix git: error: unable to locate xcodebuild
if [ "$(xcode-select -p)" != /Library/Developer/CommandLineTools ]; then
	sudo xcode-select --switch /Library/Developer/CommandLineTools/
fi

# Generate locate database
if [ ! -f /var/db/locate.database ]; then
	sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.locate.plist
	echo locate database is going to be generated.
fi

dir="$(dirname "$0")"

# setup zsh
$dir/zsh_setup.sh

# setup bash
$dir/bash_setup.sh
