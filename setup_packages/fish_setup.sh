#!/usr/bin/env bash

# Install ohmyfish if not already installed
if [ ! -d $HOME/.local/share/omf ]; then
    # Using socks proxy
    . set_proxy
    curl_socks -L https://get.oh-my.fish | fish
fi

# Install fisher (A package manager for the fish shell) if not already installed
if [ ! -f ~/.config/fish/functions/fisher.fish ]; then
    . set_proxy
    curl_socks https://git.io/fisher --create-dirs -sLo ~/.config/fish/functions/fisher.fish
fi

fish <<-"EOF"
    # Install packages using omf
    set packages_to_install \
        gnuykeaj \
            # Super minimal one line version of clearance theme
        tomita \
            # A minimal, aesthetically pleasing fish theme
        default

    for package in $packages_to_install
        omf install $package
    end

    # Install plugins using fisher
    set plugins_to_install \
        jorgebucaran/fish-bax \
            # Run bash utilities right from your fish shell
        jethrokuan/z \
            # z is a port of z for the fish shell
        barnybug/docker-fish-completion
            # docker command completion for the fish shell

    for plugin in $plugins_to_install
        fisher add $plugin
    end
EOF
