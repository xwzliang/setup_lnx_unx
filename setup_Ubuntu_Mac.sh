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
	elinks	# Full-Featured Text web Browser, advanced and well-established feature-rich text mode web browser
	shadowsocks-libev
	privoxy
	expect	# a language that talks with your interactive programs or scripts that require user interaction
	bats	# Bash Automated Testing System
	check		# A unit testing framework for C
	jq		# jq is like sed for JSON data - you can use it to slice and filter and map and transform structured data
	unrar	# For extracting rar archive files
	global	# Source code tag system
	graphviz	# open source graph visualization software. Graph visualization is a way of representing structural information as diagrams of abstract graphs and networks
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
		ack		# Search tool like grep, but optimized for programmers
		aspell
		poppler		# PDF rendering library
		gdb				# GNU debugger
		gcc			# GNU compiler collection
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
		openssh-server	# A powerful collection of tools for remote control
		net-tools
		dconf-tools		# A low-level configuration system
		bcmwl-kernel-source		# Wifi adapter for laptop
		python3-pip
		djvulibre-bin	# djvulibre including ddjvu
		calibre
		xterm
		mpv
		hfsprogs
		python3-lxml
		proxychains
		virtualbox		# A general-purpose full virtualizer
		vagrant		# A tool for building and managing virtual machine environments in a single workflow
		ruby-full
		glimpse		# A very popular UNIX indexing and query system to search quickly through entire file systems, including agrep
		valgrind	# A tool for finding memory access errors to heap memory in C and C++ programs
		ack-grep		# Search tool like grep, but optimized for programmers
		poppler-utils		# PDF rendering library
	)
	for app in "${apps_to_install[@]}"; do
		PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $app | grep "install ok installed")
		if [ "" == "$PKG_OK" ]; then
			echo -e "${app} not installed, will install it\n"
			apt install -y ${app}
		else
			echo -e "${app} already installed, will skip it"
		fi
	done
fi

# Install apps using other methods

command_exists() {
	command -v "$@" > /dev/null 2>&1
}

declare -A apps_other_methods

apps_other_methods=(
	["docker"]="wget -qO- https://get.docker.com/ | sh"
	["youtube-dl"]="curl -L https://yt-dl.org/downloads/latest/youtube-dl -o /usr/local/bin/youtube-dl && chmod a+rx /usr/local/bin/youtube-dl"
	["ceedling"]="gem install ceedling"		# Ceedling is an automated testing framework for C applications. 
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


dir="$(dirname "$0")"

# directory setup
$dir/dir_setup.sh

# git credential settings, import setting_git_credential.sh
$dir/git_setup.sh

# vim settings
$dir/vim_setup.sh

# emacs settings
$dir/emacs_setup.sh

# proxychains settings
$dir/proxychains_setup.sh

# privoxy settings
$dir/privoxy_setup.sh

# Python3 settings
$dir/python3_setup.sh

if [ "$(uname)" == "Darwin" ]; then
	# MacOS settings
	$dir/macos_setup.sh
else
	# systemd settings
	$dir/systemd_setup.sh
fi
