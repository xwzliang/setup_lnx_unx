#!/usr/bin/env bash

sudo apt install -y samba

sudo smbpasswd -a broliang

sudo tee -a /etc/samba/smb.conf <<- _EOF_
[sambashare]
    comment = Samba on Ubuntu
    path = /media
    read only = no
    browsable = yes
_EOF_

sudo service smbd restart
