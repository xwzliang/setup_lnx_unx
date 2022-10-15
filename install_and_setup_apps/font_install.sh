#!/usr/bin/env bash

cd $HOME/git/Downloads/

git clone https://github.com/xwzliang/font.git 2>/dev/null

fontDir=$HOME/.fonts
mkdir -p $fontDir

cp 'font/unicode/Microsoft Yahei.ttf' $fontDir

fc-cache -fv
