#!/usr/bin/env bash

# Use zsh as default shell
# if [[ ! "$SHELL" =~ zsh ]]; then
#   zsh_path="$( command -v zsh )"
#   sudo chsh -s "$zsh_path" $USER
#   echo "default shell changed to $zsh_path"
# fi

# Install ohmyzsh if not already installed
if [ ! -d ~/.oh-my-zsh ]; then
    # sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
    # Using socks proxy
    . set_proxy
    sh -c "$(curl_socks -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
fi

if ! grep -h zsh_aliases $HOME/.zshrc; then
    echo "source $HOME/.zsh_aliases" >> $HOME/.zshrc
fi

if ! grep -h all_sh_aliases $HOME/.zshrc; then
    echo "source $HOME/.all_sh_aliases" >> $HOME/.zshrc
fi

if ! grep -h all_sh_env $HOME/.zshenv; then
    echo "source $HOME/.all_sh_env" >> $HOME/.zshenv
fi
