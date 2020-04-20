#!/usr/bin/env bash

cd $HOME/Downloads
mkdir -p bin
cd bin

# client
aria2c https://www.realvnc.com/download/file/viewer.files/VNC-Viewer-6.19.923-Linux-x64.deb
dpkg -i VNC-Viewer-6.19.923-Linux-x64.deb

# server
aria2c https://www.realvnc.com/download/file/vnc.files/VNC-Server-6.6.0-Linux-x64.deb
dpkg -i VNC-Server-6.6.0-Linux-x64.deb
