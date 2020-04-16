#!/usr/bin/env bash

if ! grep -h bash_aliases $HOME/.bashrc; then
	echo "source $HOME/.bash_aliases" >> $HOME/.bashrc
fi

# z set up: jump around easily
if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	z_path=/usr/local/etc/bash_completion.d/z.bash
else
	# Ubuntu
	z_path=/etc/bash_completion.d/z.bash
fi

if [ ! -f $z_path ]; then
	sudo wget -O $z_path https://raw.githubusercontent.com/rupa/z/master/z.sh
fi

command_exists() {
	command -v "$@" > /dev/null 2>&1
}

dir="$(dirname "$0")"

# Install bashdb if not already
if ! command_exists bashdb; then
	$dir/install_apps/bashdb_install.sh
fi
