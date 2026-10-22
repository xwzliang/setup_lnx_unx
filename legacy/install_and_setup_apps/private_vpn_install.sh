#!/usr/bin/env bash

sudo apt-get install openvpn -y

download_bin_dir=$HOME/Downloads/bin/private_vpn
mkdir -p $download_bin_dir
cd $download_bin_dir

. set_privoxy

curl_socks -O https://privatevpn.com/client/install.sh
sudo chmod +x install.sh
sudo ./install.sh

exit
