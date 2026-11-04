#!/usr/bin/env bash

# Swap control and command key for windows keyboard layout
# Caps Lock as escape

cat<< EOF > ~/.Xmodmap
clear control
clear mod4

keycode 105 =
keycode 206 =

keycode 133 = Control_L NoSymbol Control_L
keycode 134 = Control_R NoSymbol Control_R
keycode 37 = Super_L NoSymbol Super_L

add control = Control_L
add control = Control_R
add mod4 = Super_L

clear Lock
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
