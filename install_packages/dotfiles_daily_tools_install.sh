#!/usr/bin/env bash

mkdir -p ~/git
cd ~/git

sudo apt install -y git

git clone https://github.com/xwzliang/dotfiles.git
git clone https://github.com/xwzliang/daily_tools

cd ~/git/dotfiles
./install.sh

cd ~/git/daily_tools
./install.sh
