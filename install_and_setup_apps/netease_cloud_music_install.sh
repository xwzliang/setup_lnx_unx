#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

aria2c http://d1.music.126.net/dmusic/netease-cloud-music_1.2.1_amd64_ubuntu_20190428.deb

sudo dpkg -i netease-cloud-music_1.2.1_amd64_ubuntu_20190428.deb
