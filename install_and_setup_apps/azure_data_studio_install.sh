#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

wget -q https://sqlopsbuilds.azureedge.net/stable/13e362762762e5cb76a5c8afd2bc650f48c2d3d8/azuredatastudio-linux-1.28.0.deb
sudo dpkg -i azuredatastudio-linux-1.28.0.deb
