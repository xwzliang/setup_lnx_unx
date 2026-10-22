#!/usr/bin/env bash

apt remove zotero -y
rm -rf $HOME/.zotero $HOME/Zotero $HOME/.cache/zotero
rm -f $HOME/Downloads/bin/{zotfile*,zutilo*}
