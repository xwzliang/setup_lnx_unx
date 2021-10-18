#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

version=1.6.4

# Build the URI for the webextension file
base='https://github.com/browsh-org/browsh/releases/download'
release_url="$base/v$version/browsh_${version}_linux_amd64.deb"

curl_socks -L -O $release_url

sudo dpkg -i ./"browsh_${version}_linux_amd64.deb"
