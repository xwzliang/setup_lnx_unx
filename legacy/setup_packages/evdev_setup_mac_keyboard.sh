#!/usr/bin/env bash

# run as sudo

# Swap control and command key for mac keyboard layout
# Caps Lock as escape

evdev_path=/usr/share/X11/xkb/keycodes/evdev
evdev_bak_path=$evdev_path.bak

# back up evdev file, ask if back up file already exists
sudo cp -n $evdev_path $evdev_bak_path

sudo gawk -i inplace '
# Change CAPS using evdev in ubuntu 21.10 seems not working
# /^\t<CAPS> = 66;$/ {
#     print "	<ESC> = 66;"
#     next
# }
/^\t<LCTL> = 37;$/ {
    print "	<LWIN> = 37;"
    next
}
/^\t<LWIN> = 133;$/ {
    print "	<LCTL> = 133;"
    next
}
/^\t<RWIN> = 134;$/ {
    print "	<RCTL> = 134;"
    next
}
/.*/
' $evdev_path

# need to reboot
# reboot

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
