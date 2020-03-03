#!/usr/bin/env bash

modules_to_install=(
	numpy
	pandas
	pyzotero
	isbnlib		# isbnlib is a (pure) python library that provides several useful methods and functions to validate, clean, transform, hyphenate and get metadata for ISBN strings.
	beautifulsoup4		# Beautiful Soup is a library that makes it easy to scrape information from web pages.
)

for module in "${modules_to_install[@]}"; do
	if python3 -c "import $module" > /dev/null 2>&1; then
		echo "$module already installed."
	else
		pip3 install $module
	fi
done
