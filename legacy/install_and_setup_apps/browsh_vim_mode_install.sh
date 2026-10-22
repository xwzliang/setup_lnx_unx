#!/usr/bin/env bash

download_bin_dir=$HOME/go/src
mkdir -p $download_bin_dir
cd $download_bin_dir

git clone -b vim-mode-experimental --single-branch https://github.com/browsh-org/browsh.git

# Setting up dependencies
REPO_ROOT=$download_bin_dir/browsh
cd $REPO_ROOT/webext
source ~/.nvm/nvm.sh # this is optional
# npm run get-gobindata
npm install
npm run build
diff -u <(echo -n) <(gofmt -d ./)
./node_modules/.bin/prettier --list-different "{src,test}/**/*.js"


set -e

INTERFACER_ROOT=$REPO_ROOT/interfacer
cd $INTERFACER_ROOT

# Get the current Browsh version, in order to find the corresponding web extension release
version_file=$INTERFACER_ROOT/src/browsh/version.go
line=$(cat $version_file | grep 'browshVersion')
version=$(echo $line | grep -o '".*"' | sed 's/"//g')

# Build the URI for the webextension file
base='https://github.com/browsh-org/browsh/releases/download'
release_url="$base/v$version/browsh-${version}-an.fx.xpi"

xpi_file=$INTERFACER_ROOT/browsh.xpi
destination=$INTERFACER_ROOT/src/browsh/webextension.go

# Download the web extension
curl_socks -L -o $xpi_file $release_url

# Convert the web extension into binary data that can be compiled into a
# cross-platform Go binary.
XPI_FILE=$xpi_file BIN_FILE=$destination \
  $INTERFACER_ROOT/contrib/xpi2bin.sh

# Building browsh
cd $REPO_ROOT/interfacer && dep ensure -v
echo "go Done"
GO111MODULE=off go build -o browsh src/main.go

# Copy the bin
cp $REPO_ROOT/interfacer/browsh ~/bin

# Building the web extension
# cd $REPO_ROOT/webext
# webpack --watch

# Run firefox and the webextension (open another window and manually run this)
# cd $REPO_ROOT/webext/dist
# web-ext run --verbose

# Run browsh (open another window and manually run this)
# cd $REPO_ROOT/interfacer
# ./browsh
