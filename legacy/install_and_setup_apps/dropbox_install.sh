#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

proxychains wget -O dropbox.tar.gz "https://www.dropbox.com/download?plat=lnx.x86_64" 
tar xzf dropbox.tar.gz

# to run the dropbox daemon
# .dropbox-dist/dropboxd
timeout 10 .dropbox-dist/dropboxd

# Use the dropbox package python script
dropbox_script=/usr/local/bin/dropboxd
proxychains wget -O $dropbox_script "https://linux.dropbox.com/packages/dropbox.py"
chmod +x $dropbox_script

dir="$(dirname "$0")"

$dir/dropboxd_setup.sh
