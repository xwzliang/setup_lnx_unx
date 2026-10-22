#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

wget -q https://sqlopsbuilds.azureedge.net/stable/4a45ba7cf20dd4129f1a08e5e776dfb33e3d1d1e/azuredatastudio-linux-1.32.0.deb
sudo dpkg -i azuredatastudio-linux-1.32.0.deb
