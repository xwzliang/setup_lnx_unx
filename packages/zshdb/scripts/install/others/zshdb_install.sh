#!/usr/bin/env bash

# Install zshdb: gdb-like "trepan" debugger for zsh

if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	HOMEBREW_NO_AUTO_UPDATE=1 brew install ---with-pcre zshdb
else
	# Ubuntu
	sudo apt-get install -y zshdb
fi
