#!/usr/bin/env bash

add-apt-repository ppa:bitcoin/bitcoin -y
apt-get update
apps_to_install=(
	build-essential libtool autotools-dev automake pkg-config bsdmainutils	# Bitcoin Core Build Required
	libssl-dev libevent-dev libboost-system-dev libboost-filesystem-dev libboost-chrono-dev libboost-program-options-dev libboost-test-dev libboost-thread-dev libminiupnpc-dev libzmq3-dev	# Bitcoin Core dependencies
	libqt5gui5 libqt5core5a libqt5dbus5 qttools5-dev qttools5-dev-tools libprotobuf-dev protobuf-compiler libqrencode-dev	# Bitcoin Core qt5
	libdb4.8-dev libdb4.8++-dev		# libdb_cxx via ppa: required by Bitcoin Core build
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

download_bin_dir=$HOME/Downloads/bin
mkdir -p $download_bin_dir
cd $download_bin_dir

if [ ! -d bitcoin ]; then
	proxychains git clone "https://github.com/bitcoin/bitcoin.git"
	cd bitcoin
	git checkout `git tag --sort=taggerdate | grep -v rc | grep -v test | tail -1`
else
	cd bitcoin
fi

./autogen.sh
./configure
make
make install
