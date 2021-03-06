#!/usr/bin/env bash

command_exists() {
    command -v "$@" > /dev/null 2>&1
}

# Install homebrew for linux and macos
if ! command_exists brew; then
    echo -e "brew not installed, will install it\n"
    /bin/bash -c "$(curl_socks -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
else
    echo "brew already installed, will skip it"
fi

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
    sox		      # Swiss army knife of sound processing
    libsox-fmt-mp3		      # SoX MP2 and MP3 format library
    mplayer			# video and audio player for Unix-like systems
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
    tree			# a recursive directory listing command that produces a depth indented listing of files
    pdsh			# Efficient rsh-like utility, for using hosts in parallel
    p7zip			# p7zip is the Unix command-line port of 7-Zip, a file archiver that handles the 7z format which features very high compression ratios
    scala			# Scala is a Java-compatible programming language with many modern language features
    ansible			# Configuration management, deployment, and task execution system
    postgresql		# object-relational SQL database
)

if [ "$(uname)" == "Darwin" ]; then
    # MacOS
    taps_to_tap=(
        mongodb/brew
    )

    for tap in "${taps_to_tap[@]}"; do
        brew tap $tap
    done

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
        mysql					# a fast, stable and true multi-user, multi-threaded SQL database server
        mongodb-community		# object/document-oriented database
        gpick					# advanced GTK+ color picker
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
        # calibre
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
        default-jre             # default Java Runtime Environment (JRE)
        default-jdk             # default Java Development Kit (JDK)
        p7zip-full				# p7zip-full provides utilities to pack and unpack 7z archives within a shell or using a GUI (such as Ark, File Roller or Nautilus), Additionally, it provides the 7z and 7za commands
        mysql-server			# a fast, stable and true multi-user, multi-threaded SQL database server
        mongodb					# object/document-oriented database
        cheese					# tool to take pictures and videos from your webcam
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
