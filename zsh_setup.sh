#!/usr/bin/env bash

if ! grep -h bash_aliases $HOME/.zshrc; then
	echo "source $HOME/.bash_aliases" >> $HOME/.zshrc
fi
