#!/usr/bin/env bash

proxychains_conf=/etc/proxychains.conf
proxychains_conf_bak=/etc/proxychains.conf.bak

if [ ! -e $proxychains_conf_bak ]; then
	cp $proxychains_conf $proxychains_conf_bak
fi

if [[ "`tail -2 $proxychains_conf`" =~ ^socks4.* ]]; then
	# change the second last line using tac and sed
	tac $proxychains_conf_bak | sed '2s/^.*$/socks5 127.0.0.1 1080/' | tac > $proxychains_conf
fi

# To test, run:
# proxychains curl https://www.google.com
