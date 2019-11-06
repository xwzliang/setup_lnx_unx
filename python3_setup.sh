#!/usr/bin/env bash

modules_to_install=(
	numpy
	pandas
)

for module in "${modules_to_install[@]}"; do
	if pip3 list --format=columns | grep "$module" > /dev/null; then
		echo "$module already installed."
	else
		pip3 install $module
	fi
done
