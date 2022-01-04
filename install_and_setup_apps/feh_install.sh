#!/usr/bin/env bash

download_bin_dir=$HOME/git/Downloads
mkdir -p $download_bin_dir
cd $download_bin_dir

git clone https://github.com/derf/feh.git

sudo apt install -y libxinerama-dev libimlib2-dev libcurl4-openssl-dev libpng-dev libx11-dev

cd feh
make
sudo make install app=1
