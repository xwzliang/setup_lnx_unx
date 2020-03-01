#!/usr/bin/env bash

modules_to_install=(
	numpy
	pandas
	pyzotero
)

for module in "${modules_to_install[@]}"; do
	if python3 -c "import $module" > /dev/null; then
		echo "$module already installed."
	else
		pip3 install $module
	fi
done
