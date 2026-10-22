#!/usr/bin/env bash

dir="$(dirname "$0")"
install_dir=$dir/../install_packages
setup_dir=$dir/../setup_packages

sudo apt install -y shadowsocks-libev privoxy proxychains trojan

# proxychains settings
sudo $setup_dir/proxychains_setup.sh

# privoxy settings
sudo $setup_dir/privoxy_setup.sh

