#!/usr/bin/env bash

# Important!! This script must not be run by root

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

# Downloaded version from the Zotero website
# file=Zotero-5.0.74_linux-x86_64.tar.bz2
# if [ ! -e $file ]; then
	# wget -O $file 'https://www.zotero.org/download/client/dl?channel=release&platform=linux-x86_64&version=5.0.74'
# fi
# tar xjf $file

# cd Zotero_linux-x86_64
# ./zotero

# Packaged versions of Zotero and Juris-M for Debian-based systems
wget -qO- https://github.com/retorquere/zotero-deb/releases/download/apt-get/install.sh | sudo bash
sudo apt update
sudo apt install zotero
# If error "your profile cannot be loaded" occurs, run:
# rm -rf ~/.zotero
# rm -rf ~/.cache/zotero

# Run zotero for first time to allow it generate its folders
timeout 5s zotero

# Download Zotfile
sudo wget 'https://github.com/jlegewie/zotfile/releases/download/v5.0.10/zotfile-5.0.10-fx.xpi'

# Download Zutilo to find all attachments files moved by zotfiles
sudo wget 'https://github.com/willsALMANJ/Zutilo/releases/download/v3.2.1/zutilo.xpi'

# Install zotero-cli: A simple command-line interface for the Zotero API.
pip3 install zotero-cli
zotcli configure
