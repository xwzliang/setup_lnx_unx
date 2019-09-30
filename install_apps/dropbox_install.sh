#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

proxychains wget -O dropbox.tar.gz "https://www.dropbox.com/download?plat=lnx.x86_64" 
tar xzf dropbox.tar.gz

# to run the dropbox daemon
# .dropbox-dist/dropboxd
