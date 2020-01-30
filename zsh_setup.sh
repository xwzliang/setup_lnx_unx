#!/usr/bin/env bash

if ! grep -h zsh_aliases $HOME/.zshrc; then
	echo "source $HOME/.zsh_aliases" >> $HOME/.zshrc
fi
