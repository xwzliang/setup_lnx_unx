#!/usr/bin/env bash

modules_to_install=(
    coursera-dl
    apt-mirror-updater			# Automated, robust apt-get mirror selection for Debian and Ubuntu. Usage: sudo apt-mirror-updater -c "http://mirrors.aliyun.com/ubuntu/"
    pulsemixer			# CLI and curses mixer for PulseAudio, useful to change ubuntu sound volume manually or via command.
    rerun				# Command-line script to re-run the given command when files change
    numpy
    pandas
    # pyzotero
    # isbnlib		# isbnlib is a (pure) python library that provides several useful methods and functions to validate, clean, transform, hyphenate and get metadata for ISBN strings.
    # beautifulsoup4		# Beautiful Soup is a library that makes it easy to scrape information from web pages.
    virtualenv			# a tool to create isolated Python environments
    pipenv				# Python Dev Workflow for Humans
    jedi				# Jedi is a static analysis tool for Python that is typically used in IDEs/editors plugins. Jedi has a focus on autocompletion and goto functionality.
    rope				# a python refactoring library
    trepan3k			# A gdb-like Python3 Debugger in the Trepan family
    black				# The uncompromising code formatter
    isort				# A Python utility / library to sort imports
    flake8				# flake8 is a python tool that glues together pep8, pyflakes, mccabe, and third-party plugins to check the style and quality of some python code
    python-lsp-server[all]		# Fork of the python-language-server project, maintained by the Spyder IDE team and the community
    pyright						# Static type checker for Python
    docker-compose				# Define and run multi-container applications with Docker
    lastversion					# Fetch latest release version of an arbitrary project
    # mrjob						# mrjob is a Python 2.7/3.4+ package that helps you write and run Hadoop Streaming jobs.
    # pyspark						# Python API for Spark
    # selenium					# Python language bindings for Selenium WebDriver
    # pymongo						# Python driver for MongoDB
    # awsebcli					# The AWS Elastic Beanstalk Command Line Interface (EB CLI) is a tool that helps you deploy and manage your Elastic Beanstalk applications and environments
    # django						# Django is a high-level Python Web framework that encourages rapid development and clean, pragmatic design
    # mongoengine					# MongoEngine is a Python Object-Document Mapper for working with MongoDB
    # djangorestframework			# Django REST framework is a powerful and flexible toolkit for building Web APIs
    # django-rest-framework-mongoengine			# The package provides mongoengine support for django-rest-framework
    # flask						# Flask is a lightweight WSGI web application framework
    # xlrd						# for Excel support
    # openpyxl					# for Excel support
    scikit-learn 				# machine learning in Python
    matplotlib					# a comprehensive library for creating static, animated, and interactive visualizations in Python
)

for module in "${modules_to_install[@]}"; do
    if python3 -c "import $module" > /dev/null 2>&1; then
        echo "$module already installed."
    else
        pip3 install $module
    fi
done
