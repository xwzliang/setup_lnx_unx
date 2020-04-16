#!/usr/bin/env bash

# Fix git: error: unable to locate xcodebuild
if [ "$(xcode-select -p)" != /Library/Developer/CommandLineTools ]; then
	sudo xcode-select --switch /Library/Developer/CommandLineTools/
fi

# Generate locate database
if [ ! -f /var/db/locate.database ]; then
	sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.locate.plist
	echo locate database is going to be generated.
fi
