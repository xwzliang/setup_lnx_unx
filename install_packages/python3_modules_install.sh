#!/usr/bin/env bash

modules_to_install=(
    numpy
    pandas
    pyzotero
    isbnlib		# isbnlib is a (pure) python library that provides several useful methods and functions to validate, clean, transform, hyphenate and get metadata for ISBN strings.
    beautifulsoup4		# Beautiful Soup is a library that makes it easy to scrape information from web pages.
    virtualenv			# a tool to create isolated Python environments
    jedi				# Jedi is a static analysis tool for Python that is typically used in IDEs/editors plugins. Jedi has a focus on autocompletion and goto functionality.
    rope				# a python refactoring library
    trepan3k			# A gdb-like Python3 Debugger in the Trepan family
    black				# The uncompromising code formatter
    isort				# A Python utility / library to sort imports
    flake8				# flake8 is a python tool that glues together pep8, pyflakes, mccabe, and third-party plugins to check the style and quality of some python code
    docker-compose				# Define and run multi-container applications with Docker
    lastversion					# Fetch latest release version of an arbitrary project
)

for module in "${modules_to_install[@]}"; do
    if python3 -c "import $module" > /dev/null 2>&1; then
        echo "$module already installed."
    else
        pip3 install $module
    fi
done
