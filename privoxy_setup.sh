#!/usr/bin/env bash

socks5_setting='forward-socks5 / 127.0.0.1:1080 .'
privoxy_config=/etc/privoxy/config

if ! grep -q "$socks5_setting" "$privoxy_config"; then
	echo $socks5_setting >> $privoxy_config
fi

systemctl start privoxy.service
# systemctl -l status privoxy.service
