#!/usr/bin/env bash

if ! grep -h bash_aliases $HOME/.bashrc; then
	echo "source $HOME/.bash_aliases" >> $HOME/.bashrc
fi
