#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

## Clashy
version=$(curl -fLs https://api.github.com/repos/SpongeNobody/Clashy/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].removeprefix("v"))')

aria2c https://github.com/SpongeNobody/Clashy/releases/download/v$version/Clashy_"$version"_amd64.deb

sudo dpkg -i Clashy_"$version"_amd64.deb
