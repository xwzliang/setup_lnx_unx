#!/usr/bin/env bash

# Install bashdb: bash debugger

cd $HOME/Downloads/bin

version=5.0-1.1.2
package_name=bashdb-$version
tar_name=$package_name.tar.gz

wget https://sourceforge.net/projects/bashdb/files/bashdb/$version/$tar_name

tar xf $tar_name

cd $package_name

./configure
make
sudo make install
