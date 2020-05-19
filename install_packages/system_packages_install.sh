#!/usr/bin/env bash

# Add ppa repos
# ppa_to_add=(
# )
# for app in "${ppa_to_add[@]}"; do
    # if ! grep -q "^deb .*${app}" /etc/apt/sources.list /etc/apt/sources.list.d/*; then
        # # commands to add the ppa ...
        # add-apt-repository ppa:${app} -y
    # fi
# done

# apt-get update

apps_to_install=(
    git
    curl
    vim
    emacs
    python3
    tmux
    aria2
    pandoc
    w3m
    imagemagick
    ffmpeg
    mosh
    ocrmypdf
    rename
    elinks      # Full-Featured Text web Browser, advanced and well-established feature-rich text mode web browser
    shadowsocks-libev
    privoxy
    expect      # a language that talks with your interactive programs or scripts that require user interaction
    bats        # Bash Automated Testing System
    check		# A unit testing framework for C
    jq          # jq is like sed for JSON data - you can use it to slice and filter and map and transform structured data
    unrar       # For extracting rar archive files
    global      # Source code tag system
    graphviz	# open source graph visualization software. Graph visualization is a way of representing structural information as diagrams of abstract graphs and networks
    fzf			# fzf is a general-purpose command-line fuzzy finder.
    ack			# Search tool like grep, but optimized for programmers
    git-flow			# Git extensions to provide high-level repository operations for Vincent Driessen's branching model
    bash-completion			# Programmable completion functions for bash
    ripgrep			# ripgrep recursively searches directories for a regex pattern (faster than ag)
    zsh			# Zsh is a shell designed for interactive use, although it is also a powerful scripting language
    clang-format			# Tool to format C/C++/Obj-C code
    fish			# fish is a smart and user-friendly command line shell for Linux, macOS, and the rest of the family
    cmake			# cross-platform, open-source make system
)

if [ "$(uname)" == "Darwin" ]; then
    # MacOS
    apps_to_install+=(
        bash
        coreutils
        grep
        gnu-sed
        gawk
        findutils
        gnu-tar
        autoconf
        automake
        docker
        youtube-dl
        proxychains-ng
        aspell
        poppler                 # PDF rendering library
        gdb                     # GNU debugger
        gcc                     # GNU compiler collection
        ncurses                 # The ncurses library routines are a terminal-independent method of updating character screens with reasonable optimization.
        the_silver_searcher		# A code-searching tool similar to ack, but faster
        readline				# GNU readline and history libraries
        pyenv					# Simple Python version management
        go						# An open source programming language that makes it easy to build simple, reliable, and efficient software
        shfmt					# A shell parser, formatter and interpreter (POSIX/Bash/mksh)
        libvterm                # abstract terminal library
        cask                    # Project management tool for Emacs
    )
    for app in "${apps_to_install[@]}"; do
        if brew ls --versions ${app} > /dev/null; then
            echo -e "${app} already installed, will skip it"
        else
            if brew info ${app} > /dev/null 2>&1 ; then
                echo -e "${app} not installed, will install it\n"
                HOMEBREW_NO_AUTO_UPDATE=1 brew install ${app}
            else
                echo "${app} is not available in homebrew."
            fi
        fi
    done
else
    # Ubuntu
    apps_to_install+=(
        openssh-server          # A powerful collection of tools for remote control
        net-tools
        bcmwl-kernel-source		# Wifi adapter for laptop
        nautilus-admin			# Extension for Nautilus to do administrative operations
        python3-pip
        djvulibre-bin           # djvulibre including ddjvu
        calibre
        xterm
        mpv
        hfsprogs
        python3-lxml
        proxychains
        virtualbox              # A general-purpose full virtualizer
        vagrant                 # A tool for building and managing virtual machine environments in a single workflow
        ruby-full
        glimpse                 # A very popular UNIX indexing and query system to search quickly through entire file systems, including agrep
        valgrind                # A tool for finding memory access errors to heap memory in C and C++ programs
        poppler-utils           # PDF rendering library
        anki                    # Anki is a program designed to help you remember facts as easily, quickly and efficiently as possible
        apt-file                # apt-file is a command line tool for searching files contained in packages for the APT packaging system. You can search in which package a file is included or list the contents of a package without installing or fetching it.
        libncurses-dev          # The ncurses library routines are a terminal-independent method of updating character screens with reasonable optimization.
        silversearcher-ag		# A code-searching tool similar to ack, but faster
        libbz2-dev              # bzip2 compressor library
        libreadline-dev         # GNU readline and history libraries
        libsqlite3-dev          # SQLite 3 development files
        docker.io
        libvterm-dev            # abstract terminal library
        at                      # Delayed job execution
    )
    for app in "${apps_to_install[@]}"; do
        PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $app | grep "install ok installed")
        if [ "" == "$PKG_OK" ]; then
            echo -e "${app} not installed, will install it\n"
            sudo apt install -y ${app}
        else
            echo -e "${app} already installed, will skip it"
        fi
    done
fi

# Install apps using other methods

# Source ~/.all_sh_aliases because some commands will be a shell function
source $HOME/.all_sh_aliases

command_exists() {
    command -v "$@" > /dev/null 2>&1
}

dir="$(dirname "$0")"

declare -A apps_other_methods

apps_other_methods=(
    # ["docker"]="wget -qO- https://get.docker.com/ | sh"
    ["youtube-dl"]="curl -L https://yt-dl.org/downloads/latest/youtube-dl -o /usr/local/bin/youtube-dl && chmod a+rx /usr/local/bin/youtube-dl"
    ["ceedling"]="gem install ceedling"		# Ceedling is an automated testing framework for C applications.
    ["pyenv"]="curl_socks -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash"		# Simple Python version management
    ["zshdb"]="$dir/others/zshdb_install.sh"
    ["bashdb"]="$dir/others/bashdb_install.sh"
    ["tiv"]="$dir/others/tiv_install.sh"
    ["go"]="sudo snap install --classic go"
    ["shfmt"]="sudo snap install shfmt"
    ["nix"]="sh <(curl https://nixos.org/nix/install)"		# Nix, the purely functional package manager
    ["nvm"]="curl_socks -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.35.3/install.sh | bash"		# Node Version Manager
    ["node"]="nvm install node"                           # an open-source, cross-platform, JavaScript runtime environment
    ["npm"]="curl -L https://www.npmjs.com/install.sh | sh"             # the Node.js package manager
    ["cask"]="curl_socks -fsSL https://raw.githubusercontent.com/cask/cask/master/go | python"             # Project management tool for Emacs
)

for app_other in "${!apps_other_methods[@]}"; do
    if ! command_exists $app_other; then
        echo -e "${app_other} not installed, will install it\n"
        eval ${apps_other_methods[$app_other]}
    else
        echo -e "${app_other} already installed, will skip it"
    fi
done


# Clone repository using git

declare -A repos_git_clone

repos_git_clone=(
    ["$HOME/.tmux/plugins/tpm"]="https://github.com/tmux-plugins/tpm"
)

for directory_git_local in "${!repos_git_clone[@]}"; do
    if [ ! -d $directory_git_local ]; then
        echo -e "${directory_git_local} not exists, will clone it using git\n"
        git clone ${repos_git_clone[$directory_git_local]} $directory_git_local
    else
        echo -e "${directory_git_local} already exists, will skip it"
    fi
done
