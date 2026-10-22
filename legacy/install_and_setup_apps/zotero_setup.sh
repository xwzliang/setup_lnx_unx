#!/usr/bin/env bash

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir


# Make symlink between Zotero storage and Dropbox
ln -sf $HOME/Dropbox/storage ../../Zotero/storage

listen_port=1080

# Find zotero preference file path
if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	preference_path_prefix="$HOME/Library/Application Support/Zotero/Profiles"
else
	# Ubuntu
	preference_path_prefix=$HOME/.zotero/zotero
fi
# grep its folder name
preference_folder_name=$(ls "$preference_path_prefix" | grep default)
preference_folder_path="$preference_path_prefix"/$preference_folder_name
preference_file="$preference_folder_path/prefs.js"
echo "zotero preference file path is $preference_file"
# Create extension folder
extension_folder="$preference_folder_path/extensions"
mkdir -p "$extension_folder"


user_me=$(echo $HOME | cut -d / -f 3)

# Create books dir for books and use as zotfile source folder
books_path=$HOME/Downloads/books
mkdir -p $books_path
chown $user_me $books_path

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
user_pref("network.proxy.socks", "127.0.0.1");
user_pref("network.proxy.socks_port", "$listen_port");
user_pref("network.proxy.type", 1);
user_pref("extensions.zotero.baseAttachmentPath", "$HOME/Dropbox/ZoteroStorage");
_EOF_
)

# Add preferences
while read -r line; do
	if ! grep -q "$line" "$preference_file"; then
		echo "$line" >> "$preference_file"
	fi
done <<< "$preferences"


# Install Zotfile 
cp $download_bin_dir/zotfile*.xpi "$extension_folder/zotfile@columbia.edu.xpi"

# Install zutilo 
cp $download_bin_dir/zutilo.xpi "$extension_folder/zutilo@www.wesailatdawn.com.xpi"


# If attachments pdf cannot be opened, do following:
# Select all items in library, right click attachment, use zutilo's command "Modify attachment paths", in "Old partial path to attachments' directory to be replaced:" enter: "attachments:" (or whatever path prefix showed by zutilo' "Show attachment paths"), in "New partial path to be used ...", enter the directory (/home/my_username/Dropbox/ZoteroStorage/)

