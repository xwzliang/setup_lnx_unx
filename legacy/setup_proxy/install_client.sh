#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

## Clashy
version=$(get_github_latest_release SpongeNobody/Clashy)

aria2c https://github.com/SpongeNobody/Clashy/releases/download/v$version/Clashy_"$version"_amd64.deb

sudo dpkg -i Clashy_"$version"_amd64.deb
