#!/usr/bin/env bash

cd $HOME/Downloads
mkdir -p bin
cd bin

# client
# aria2c https://www.realvnc.com/download/file/viewer.files/VNC-Viewer-6.19.923-Linux-x64.deb
# dpkg -i VNC-Viewer-6.19.923-Linux-x64.deb

server_version=6.8.0
# server
aria2c https://www.realvnc.com/download/file/vnc.files/VNC-Server-$server_version-Linux-x64.deb
sudo dpkg -i VNC-Server-$server_version-Linux-x64.deb
