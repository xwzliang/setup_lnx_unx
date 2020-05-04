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

# Clone plugins repository using git

declare -A repos_git_clone
plugin_dir=$HOME/.oh-my-zsh/custom/plugins

repos_git_clone=(
    ["zsh-autosuggestions"]="zsh-users/zsh-autosuggestions"
)

for plugin in "${!repos_git_clone[@]}"; do
    if [ ! -d "$plugin_dir/$plugin" ]; then
        echo -e "${plugin} not exists, will clone it using git\n"
        git clone "https://github.com/${repos_git_clone[$plugin]}" "$plugin_dir/$plugin"
    else
        echo -e "${plugin} already exists, will skip it"
    fi
done


if ! grep -h zsh_aliases $HOME/.zshrc; then
    echo "source $HOME/.zsh_aliases" >> $HOME/.zshrc
fi

if ! grep -h all_sh_aliases $HOME/.zshrc; then
    echo "source $HOME/.all_sh_aliases" >> $HOME/.zshrc
fi

if ! grep -h all_sh_env $HOME/.zshenv; then
    echo "source $HOME/.all_sh_env" >> $HOME/.zshenv
fi
