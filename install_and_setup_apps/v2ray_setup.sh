#!/usr/bin/env bash

ip="$1"
port="$2"
id="$3"
# alterId default 64 if not specified.
alterId="${4:-64}"

if [ "$(uname)" == "Darwin" ]; then
	# MacOS
	config_path=/usr/local/etc/v2ray/config.json
else
	# Ubuntu
	config_path=/etc/v2ray/config.json
fi

listen_port=1080

if [ ! -f $config_path ]; then
	config_path=$PWD/config.json
	echo "config is installed in $config_path as config.json"
	if [ -f $PWD/config.json ]; then
		mv $PWD/config.json $PWD/config.json.bak
	fi
else
	is_system_install=true
	mv $config_path $config_path.bak
fi

cat << _EOF_ > $config_path
{
  "inbounds": [
    {
      "port": "$listen_port", // listening port
      "protocol": "socks", // SOCKS 5
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls"]
      },
      "settings": {
        "auth": "noauth"
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "vmess", 
      "settings": {
        "vnext": [
          {
            "address": "$ip", // address of server, change this
            "port": $port,  // port of server, change this
            "users": [
              {
                "id": "$id",  // server ID, should be the same with server, change this
                "alterId": $alterId // same with server, change this
              }
            ]
          }
        ]
      }
    }
  ]
}
_EOF_

if [ "$is_system_install" == true ]; then
	if [ "$(uname)" == "Darwin" ]; then
		# MacOS
		brew services restart v2ray-core
	else
		# Ubuntu
		systemctl restart v2ray
	fi
fi
