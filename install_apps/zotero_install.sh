#!/usr/bin/env bash

# Important!! This script must not be run by root

user_me=$(echo $HOME | cut -d / -f 3)

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

# Downloaded version from the Zotero website
# file=Zotero-5.0.74_linux-x86_64.tar.bz2
# if [ ! -e $file ]; then
	# wget -O $file 'https://www.zotero.org/download/client/dl?channel=release&platform=linux-x86_64&version=5.0.74'
# fi
# tar xjf $file

# cd Zotero_linux-x86_64
# ./zotero

# Packaged versions of Zotero and Juris-M for Debian-based systems
wget -qO- https://github.com/retorquere/zotero-deb/releases/download/apt-get/install.sh | sudo bash
sudo apt update
sudo apt install zotero
# If error "your profile cannot be loaded" occurs, run:
# rm -rf ~/.zotero
# rm -rf ~/.cache/zotero

# Run zotero for first time to allow it generate its folders
timeout 5s zotero

# Make symlink between Zotero storage and Dropbox
ln -s $HOME/Dropbox/storage ../../Zotero/storage

# grep its folder name in .zotero
preference_folder_name=$(ls $HOME/.zotero/zotero | grep default)

# Create extension folder
extension_folder=$HOME/.zotero/zotero/$preference_folder_name/extensions
sudo mkdir -p $extension_folder

# Download Zotfile
sudo wget 'https://github.com/jlegewie/zotfile/releases/download/v5.0.10/zotfile-5.0.10-fx.xpi'
# Install Zotfile
sudo cp zotfile*.xpi $extension_folder/zotfile@columbia.edu.xpi

# Create books dir for books and use as zotfile source folder
books_path=$HOME/Downloads/books
mkdir -p $books_path
chown $user_me $books_path

# Download Zutilo to find all attachments files moved by zotfiles
sudo wget 'https://github.com/willsALMANJ/Zutilo/releases/download/v3.2.1/zutilo.xpi'
sudo cp zutilo.xpi $extension_folder/zutilo@www.wesailatdawn.com.xpi

# Add prefereces to zotero
preferences=$(cat << _EOF_
user_pref("extensions.zotero.downloadAssociatedFiles", false);
user_pref("extensions.zotero.sync.fulltext.enabled", false);
user_pref("extensions.zotero.sync.server.username", "broliang");
user_pref("extensions.zotero.sync.storage.enabled", false);
user_pref("extensions.zoteroOpenOfficeIntegration.skipInstallation", true);
user_pref("extensions.zotfile.confirmation", false);
user_pref("extensions.zotfile.dest_dir", "$HOME/Dropbox/ZoteroStorage");
user_pref("extensions.zotfile.import", false);
user_pref("extensions.zotfile.source_dir", "$books_path");
user_pref("extensions.zotfile.source_dir_ff", false);
user_pref("extensions.zotfile.tablet", true);
user_pref("extensions.zotfile.tablet.dest_dir", "$HOME/Dropbox/Zotfile_tablet");
user_pref("extensions.zutilo.itemmenu.modifyAttachments", "Zutilo");
user_pref("extensions.zutilo.itemmenu.showAttachments", "Zutilo");
_EOF_
)
preference_file=$HOME/.zotero/zotero/$preference_folder_name/prefs.js

while read -r line; do
	if ! grep -q "$line" $preference_file; then
		echo "$line" >> $preference_file
	fi
done <<< "$preferences"

# If attachments pdf cannot be opened, do following:
# Select all items in library, right click attachment, use zutilo's command "Modify attachment paths", in "Old partial path to attachments' directory to be replaced:" enter: "attachments:" (or whatever path prefix showed by zutilo' "Show attachment paths"), in "New partial path to be used ...", enter the directory (/home/my_username/Dropbox/ZoteroStorage/)

# Install zotero-cli: A simple command-line interface for the Zotero API.
pip3 install zotero-cli
zotcli configure
