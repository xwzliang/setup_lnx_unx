#!/usr/bin/env bash

if ! grep -h bash_aliases $HOME/.zshrc; then
	echo "source $HOME/.bash_aliases" >> $HOME/.zshrc
fi

if ! grep -h all_sh_env $HOME/.zshenv; then
	echo "source $HOME/.all_sh_env" >> $HOME/.zshenv
fi
