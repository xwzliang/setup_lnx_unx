#!/usr/bin/env bash

if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	HOMEBREW_NO_AUTO_UPDATE=1 brew tap trojan-gfw/homebrew-trojan
	HOMEBREW_NO_AUTO_UPDATE=1 brew install trojan
else
	# Ubuntu
	sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/trojan-gfw/trojan-quickstart/master/trojan-quickstart.sh)"
fi
