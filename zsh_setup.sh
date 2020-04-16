#!/usr/bin/env bash

# Install ohmyzsh if not already installed
if [ ! -d ~/.oh-my-zsh ]; then
	# sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
	# Using socks proxy
	. set_proxy
	sh -c "$(curl_socks -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
fi

if ! grep -h bash_aliases $HOME/.zshrc; then
	echo "source $HOME/.bash_aliases" >> $HOME/.zshrc
fi

if ! grep -h all_sh_env $HOME/.zshenv; then
	echo "source $HOME/.all_sh_env" >> $HOME/.zshenv
fi

command_exists() {
	command -v "$@" > /dev/null 2>&1
}

dir="$(dirname "$0")"

# Install zshdb if not already
if ! command_exists zshdb; then
	$dir/install_apps/zshdb_install.sh
fi
