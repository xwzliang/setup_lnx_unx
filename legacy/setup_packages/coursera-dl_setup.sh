#!/usr/bin/env bash

# read -p "Enter username: " user

user=18706703437@163.com
read -p "Enter password for username $user: " pass

cat <<- _EOF_ >$HOME/.netrc
machine coursera-dl login $user password $pass
_EOF_

chmod og-rw ~/.netrc
