#!/usr/bin/env bash

# Use fish as default shell
if [[ ! "$SHELL" =~ fish ]]; then
  fish_path="$( command -v fish )"
  sudo chsh -s "$fish_path" $USER
  echo "default shell changed to $fish_path"
fi

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
        emacs \
            # This plugin replicates the functionality of the emacs plugin for oh-my-zsh
        extract \
            # Plugin to expand or extract bundled & compressed files
        fzf \
            # Ef-fish-ient fish keybindings for fzf
        python \
            # Set of shortcuts to Python based utilities (pybeatifyjson – clean JSON files, pyclean – remove old .pyc, pyhttp & pysmtp – simple HTTP & SMTP servers)
        spark \
            # ▁▂▃▅▂▇ in your shell
        weather
            # A simple, location-aware weather command for Fish

    for package in $packages_to_install
        omf install $package
    end

    # Install plugin brew for mac
    if test (uname) = "Darwin"
        omf install brew
    end

    # Install plugins using fisher
    set plugins_to_install \
        jorgebucaran/fish-bax \
            # Run bash utilities right from your fish shell
        jethrokuan/z \
            # z is a port of z for the fish shell
        jorgebucaran/fish-nvm \
            # Pure-fish, Node.js version manager
        barnybug/docker-fish-completion
            # docker command completion for the fish shell

    for plugin in $plugins_to_install
        fisher add $plugin
    end
EOF
