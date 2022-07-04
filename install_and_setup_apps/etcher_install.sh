#!/usr/bin/env bash

curl -1sLf \
   'https://dl.cloudsmith.io/public/balena/etcher/setup.deb.sh' \
    | sudo -E bash


sudo apt-get update
sudo apt-get install -y balena-etcher-electron
