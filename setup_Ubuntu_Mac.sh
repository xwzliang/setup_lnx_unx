#!/usr/bin/env bash

dir="$(dirname "$0")"
install_dir=$dir/install_packages
setup_dir=$dir/setup_packages

# locale setup
$setup_dir/locale_setup.sh

# Install dotfiles and daily_tools
$install_dir/dotfiles_daily_tools_install.sh

# Install packages
$install_dir/system_packages_install.sh

# directory setup
$setup_dir/dir_setup.sh

# bash setup
$setup_dir/bash_setup.sh

# zsh setup
$setup_dir/zsh_setup.sh

# cron setup
$setup_dir/cron_setup.sh

# git credential settings, import setting_git_credential.sh
$setup_dir/git_setup.sh

# vim settings
$setup_dir/vim_setup.sh

# emacs setup
$setup_dir/emacs_setup.sh

# proxychains settings
sudo $setup_dir/proxychains_setup.sh

# privoxy settings
sudo $setup_dir/privoxy_setup.sh

# Setup nautilus-admin
nautilus -q

# Setup Docker
sudo usermod -aG docker ${USER}

if [ "$(uname)" == "Darwin" ]; then
    # MacOS settings
    $setup_dir/macos_setup.sh
else
    # systemd settings
    # $setup_dir/systemd_setup.sh

	# Swap caps lock key and escape key
	gsettings set org.gnome.desktop.input-sources xkb-options "['caps:escape']"
fi

# Emacs install packages
$install_dir/emacs_packages_install.sh

# Python3 install packages
$install_dir/python3_modules_install.sh

# Other methods install packages
$install_dir/other_methods_packages_install.sh

# Install packages use brew
$install_dir/brew_packages_unx_lnx_install.sh

