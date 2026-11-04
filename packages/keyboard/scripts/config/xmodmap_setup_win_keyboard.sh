#!/usr/bin/env bash

# Swap control and alt key for windows keyboard layout
# Caps Lock as escape

cat<< EOF > ~/.Xmodmap
clear control
clear mod1
keycode 37 = Alt_L Meta_L
keycode 64 = Control_L
keycode 108 = Control_R
add control = Control_L Control_R
add mod1 = Alt_L Meta_L

keycode 66 = Escape NoSymbol Escape
EOF

# Change the key binding for switch applications
gsettings set org.gnome.desktop.wm.keybindings switch-applications "['<Control>Tab']"

# Change the key binding for switch applications backward
gsettings set org.gnome.desktop.wm.keybindings switch-applications-backward "['<Shift><Control>Tab']"

# Cycle windows directly
gsettings set org.gnome.desktop.wm.keybindings cycle-windows "['<Control>Escape']"
gsettings set org.gnome.desktop.wm.keybindings cycle-windows-backward "['<Shift><Control>Escape']"

# To reset
# gsettings reset org.gnome.desktop.wm.keybindings switch-applications

# To get value for a key binding
# gsettings get org.gnome.desktop.wm.keybindings switch-applications

# To list all the key binding
# gsettings list-recursively org.gnome.desktop.wm.keybindings

# To list all schemas which store keymappings
# gsettings list-schemas | grep keybindings
