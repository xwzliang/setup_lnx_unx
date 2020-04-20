#!/usr/bin/env bash

mkdir -p $HOME/Downloads/bin
cd $HOME/Downloads/bin

aria2c http://download.oray.com/peanuthull/linux/phddns_3.0_x86_64.deb
dpkg -i phddns*.deb
