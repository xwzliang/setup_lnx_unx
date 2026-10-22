#!/usr/bin/env bash

apps_to_install_brew_cask=(
	basictex
	calibre
	anki				# Need to install ankiconnect addon manually in anki to use remote api
	firefox
	google-chrome		# google-chrome cannot be downloaded when using a proxy.
    java
)

for app in "${apps_to_install_brew_cask[@]}"; do
	if brew cask ls --versions ${app} > /dev/null 2>&1; then
		echo -e "${app} already installed, will skip it"
	else
		if brew cask info ${app} > /dev/null 2>&1 ; then
			echo -e "${app} not installed, will install it\n"
			HOMEBREW_NO_AUTO_UPDATE=1 brew cask install ${app}
		else
			echo "${app} is not available in homebrew."
		fi
	fi
done
