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

# Install apps using apt
apps_to_install=(
	git
	curl
	net-tools
	openssh-server	# A powerful collection of tools for remote control
	dconf-tools		# A low-level configuration system
	bcmwl-kernel-source		# Wifi adapter for laptop
	vim
	emacs
	python3
	python3-pip
	tmux
	calibre
	aria2
	pandoc
	w3m
	xterm
	imagemagick
	ffmpeg
	mpv
	mosh
	djvulibre-bin	# djvulibre including ddjvu
	ocrmypdf
	hfsprogs
	rename
	elinks	# Full-Featured Text web Browser, advanced and well-established feature-rich text mode web browser
	python3-lxml
	proxychains
	shadowsocks-libev
	privoxy
	expect	# a language that talks with your interactive programs or scripts that require user interaction
	bats	# Bash Automated Testing System
	virtualbox		# A general-purpose full virtualizer
	vagrant		# A tool for building and managing virtual machine environments in a single workflow
	check		# A unit testing framework for C
	ruby-full
	glimpse		# A very popular UNIX indexing and query system to search quickly through entire file systems, including agrep
	jq		# jq is like sed for JSON data - you can use it to slice and filter and map and transform structured data
	unrar	# For extracting rar archive files
	valgrind	# A tool for finding memory access errors to heap memory in C and C++ programs
)

if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	for app in "${apps_to_install[@]}"; do
		if brew info ${app} > /dev/null 2>&1 ; then
			if brew ls --versions ${app} > /dev/null; then
				echo -e "${app} already installed, will skip it"
			else
				echo -e "${app} not installed, will install it\n"
				HOMEBREW_NO_AUTO_UPDATE=1 brew install ${app}
			fi
		else
			echo "${app} is not available in homebrew."
		fi
	done
else
	# Ubuntu
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
	["$HOME/.emacs.d/evil"]="https://github.com/emacs-evil/evil"
	["$HOME/.emacs.d/emms"]="git://git.sv.gnu.org/emms.git"
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

# systemd settings
$dir/systemd_setup.sh