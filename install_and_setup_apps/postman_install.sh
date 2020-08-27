#!/usr/bin/env bash

# postman: API Development Environment

if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	HOMEBREW_NO_AUTO_UPDATE=1 brew cask install postman
else
	# Ubuntu
    sudo snap install postman
fi
