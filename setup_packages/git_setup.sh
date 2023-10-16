#!/usr/bin/env bash

# Add git config
cat <<- _EOF_ >$HOME/.gitconfig
[user]
	name = broliang
	email = 18706703437@163.com
[core]
	editor = vim
[alias]
	co = checkout
	ci = commit
	br = branch
	st = status
	unstage = reset HEAD
	last = log -1
	lg = log --color --graph --pretty=format:'%C(cyan)%h%Creset -%C(yellow)%d%Creset %s %Cgreen(%cr) %C(bold blue)<%an>%Creset' --abbrev-commit
[color]
	status = always
[include]
	path = ./.gitconfig.local
[merge]
    conflictStyle = diff3
[github]
	user = xwzliang
[diff "lfs"]
	textconv = cat
_EOF_

# If socks proxy is needed, put following two lines to the config.
# [http]
# 	proxy = socks5://127.0.0.1:1080


# git credential settings
git_config_local_file=$HOME/.gitconfig.local
if [ ! -f "$git_config_local_file" ]; then
	read -rn 1 -p "Save git credentials to an unencrypted file to avoid writing? [y/N] " git_save_credential
	if [[ $git_save_credential =~ ^([Yy])$ ]]; then
		echo -e "[credential]\nhelper = store\n" > $git_config_local_file
		echo -e "\nWill save git credentials to an unencrypted file"
	else
		echo -e "[credential]\nhelper = cache --timeout 7200\n" > $git_config_local_file
		echo -e "\nWill cache credentails for two hours"
	fi
fi

git_credetial_file=$HOME/Dropbox/org/keys/git/git-credentials
if [ -f "$git_credetial_file" ]; then
    # Copy credential file
    cp $git_credetial_file ~/.git-credentials
fi

# git flow set up 
if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	gitflow_path=/usr/local/etc/bash_completion.d/git-flow-completion.bash
else
	# Ubuntu
	gitflow_path=/etc/bash_completion.d/git-flow-completion.bash
fi

cd $HOME/git/Downloads/

git clone https://github.com/bobthecow/git-flow-completion.git

cp git-flow-completion/git-flow-completion.bash $gitflow_path

# sudo wget -O $gitflow_path https://raw.githubusercontent.com/bobthecow/git-flow-completion/master/git-flow-completion.bash
