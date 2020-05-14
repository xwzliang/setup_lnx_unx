#!/usr/bin/env bash

crontab << EOF
@reboot /usr/bin/anki
@reboot /usr/local/bin/dropboxd start
@reboot /usr/bin/trojan -c $HOME/proxy/os1-2.sstr-api.xyz
@reboot /usr/bin/emacs --daemon
EOF

