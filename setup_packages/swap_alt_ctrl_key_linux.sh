#!/usr/bin/env bash

cat << EOF > $HOME/.Xmodmap
clear control
clear mod1
keycode 37 = Alt_L Meta_L
keycode 64 = Control_L
keycode 108 = Control_R
add control = Control_L Control_R
add mod1 = Alt_L Meta_L
EOF

