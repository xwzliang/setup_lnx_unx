#!/usr/bin/env bash

mkdir -p $HOME/Downloads/bin
cd $HOME/Downloads/bin

# aria2c http://download.oray.com/peanuthull/linux/phddns_3.0_x86_64.deb
aria2c https://dl-cdn.oray.com/hsk/linux/phddns-5.0.0-amd64.deb
sudo dpkg -i phddns*.deb
