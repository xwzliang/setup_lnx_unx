#!/usr/bin/env bash

proxy_dir=$HOME/proxy
mkdir -p $proxy_dir
cd $proxy_dir

wget https://github.com/v2ray/v2ray-core/releases/download/v4.20.0/v2ray-linux-64.zip

v2ray_dir=$proxy_dir/v2ray
mkdir -p $v2ray_dir

unzip v2ray-linux-64.zip -d $v2ray_dir

cat << _EOF_ >$v2ray_dir/config_me.json
{
  "inbounds": [
    {
      "port": 1080, // listening port
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
            "address": "serveraddr.com", // address of server, change this
            "port": 16823,  // port of server, change this
            "users": [
              {
                "id": "b831381d-6324-4d53-ad4f-8cda48b30811",  // server ID, should be the same with server, change this
                "alterId": 64 // same with server, change this
              }
            ]
          }
        ]
      }
    }
  ]
}
_EOF_

# To run v2ray: v2ray --config=<full path>
# $HOME/proxy/v2ray/v2ray --config=$HOME/proxy/v2ray/config_me.json

# To test if v2ray is doing its job properly, run:
# curl -4sSkL -x socks5h://127.0.0.1:1080 https://www.google.com
