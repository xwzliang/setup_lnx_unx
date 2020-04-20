#!/usr/bin/env bash

# TerminalImageViewer (tiv): Small C++ program to display images in a (modern) terminal using RGB ANSI codes and unicode block graphic characters.

if [ "$(uname)" == "Darwin" ]; then
	cd ~/git/Downloads/
	git clone https://github.com/stefanhaustein/TerminalImageViewer.git
	cd TerminalImageViewer/src/main/cpp
	gcc_version=$(ls /usr/local/Cellar/gcc)
	include_cpp_version=$(ls /usr/local/Cellar/gcc/$gcc_version/include/c++)
	include_cpp_apple_darwin_path=$(ls -d /usr/local/Cellar/gcc/$gcc_version/include/c++/$include_cpp_version/x86_64-apple-darwin*)
	CXX_version=$(sed 's/\..*//' <<< $gcc_version)
	# CXX=g++-9
	# PATH=/usr/local/Cellar/gcc/$gcc_version/bin:$PATH CPPFLAGS="-I/usr/local/Cellar/gcc/$gcc_version/include/c++/*/ -I/usr/local/Cellar/gcc/$gcc_version/include/ -I/usr/local//Cellar/gcc/$gcc_version/include/c++/*/x86_64-apple-darwin*/ -I/usr/local/Cellar/cimg/2.3.6/include/" LDFLAGS=-I/usr/local//Cellar/gcc/8.3.0/lib make
	CXX=g++-$CXX_version PATH=/usr/local/Cellar/gcc/$gcc_version/bin:$PATH CPPFLAGS="-I/usr/local/Cellar/gcc/$gcc_version/include/c++/$include_cpp_version/ -I/usr/local/Cellar/gcc/$gcc_version/include/ -I$include_cpp_apple_darwin_path" LDFLAGS=-I/usr/local/Cellar/gcc/$gcc_version/lib make
	make install
else
	sudo snap install --edge tiv
fi
