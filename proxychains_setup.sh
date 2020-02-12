#!/usr/bin/env bash

if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	proxychains_conf=/usr/local/etc/proxychains.conf
else
	# Ubuntu
	proxychains_conf=/etc/proxychains.conf
fi

proxychains_conf_bak=$proxychains_conf.bak
listen_port=1080

if [ ! -e $proxychains_conf_bak ]; then
	cp $proxychains_conf $proxychains_conf_bak
fi

if [[ "`tail -2 $proxychains_conf`" =~ ^socks4.* ]]; then
	# change the second last line using tac and sed
	tac $proxychains_conf_bak | sed '2d' | tac > $proxychains_conf
	echo "socks5 127.0.0.1 $listen_port/" >> $proxychains_conf
fi

# To test, run:
# proxychains curl https://www.google.com
