#!/usr/bin/env bash

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
