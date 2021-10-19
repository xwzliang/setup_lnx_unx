#!/usr/bin/env bash

# Install apps using other methods

command_exists() {
    command -v "$@" > /dev/null 2>&1
}

# Source ~/.all_sh_aliases because some commands will be a shell function
source $HOME/.all_sh_aliases

dir="$(dirname "$0")"

declare -A apps_other_methods

apps_other_methods=(
    # ["docker"]="wget -qO- https://get.docker.com/ | sh"
    # ["emacs"]="sudo snap install --classic emacs"
    ["youtube-dl"]="curl -L https://yt-dl.org/downloads/latest/youtube-dl -o /usr/local/bin/youtube-dl && chmod a+rx /usr/local/bin/youtube-dl"
    ["ceedling"]="gem install ceedling"		# Ceedling is an automated testing framework for C applications.
    ["pyenv"]="curl_socks -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash"		# Simple Python version management
    ["zshdb"]="$dir/others/zshdb_install.sh"
    ["bashdb"]="$dir/others/bashdb_install.sh"
    ["tiv"]="$dir/others/tiv_install.sh"
    # ["go"]="sudo snap install --classic go"
    # ["shfmt"]="sudo snap install shfmt"
    ["nix"]="sh <(curl https://nixos.org/nix/install)"		# Nix, the purely functional package manager
    ["nvm"]="curl_socks -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.35.3/install.sh | bash"		# Node Version Manager
    ["node"]="nvm install node"                           # an open-source, cross-platform, JavaScript runtime environment
    ["npm"]="curl -L https://www.npmjs.com/install.sh | sh"             # the Node.js package manager
    ["cask"]="curl_socks -fsSL https://raw.githubusercontent.com/cask/cask/master/go | python"             # Project management tool for Emacs
    ["docker-machine"]="curl_socks -L https://github.com/docker/machine/releases/download/v$(lastversion docker/machine)/docker-machine-`uname -s`-`uname -m` >/tmp/docker-machine &&
                        chmod +x /tmp/docker-machine &&
                        sudo cp /tmp/docker-machine /usr/local/bin/docker-machine"             # Machine management for a container-centric world (needs privoxy maybe)
    ["spark-shell"]="$dir/others/spark_install.sh"
    ["ebook-convert"]="sudo -v && wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin"
    ["sdk"]="curl_socks -s https://get.sdkman.io | bash"					# SDKMAN! is a tool for managing parallel versions of multiple Software Development Kits on most Unix based systems
    ["sbt"]="sdk install sbt"					# sbt is a build tool for Scala, Java, and more
    ["metals-emacs"]="$dir/others/metals-emacs_install.sh"					# Scala language server with rich IDE features
)

for app_other in "${!apps_other_methods[@]}"; do
    if ! command_exists $app_other; then
        echo -e "${app_other} not installed, will install it\n"
        eval ${apps_other_methods[$app_other]}
    else
        echo -e "${app_other} already installed, will skip it"
    fi
done

