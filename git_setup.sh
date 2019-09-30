#!/usr/bin/env bash

git config --global user.name "xwzliang"
git config --global user.email "18706703437@163.com"

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
