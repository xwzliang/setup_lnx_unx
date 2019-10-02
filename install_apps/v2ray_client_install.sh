#!/usr/bin/env bash

ip="$1"
port="$2"
id="$3"

bash <(curl -L -s https://install.direct/go.sh)

mv /etc/v2ray/config.json /etc/v2ray/config.json.bak

cat << _EOF_ >/etc/v2ray/config.json
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
            "address": "$ip", // address of server, change this
            "port": $port,  // port of server, change this
            "users": [
              {
                "id": "$id",  // server ID, should be the same with server, change this
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

systemctl start v2ray

# To test if v2ray is doing its job properly, run:
# curl -4sSkL -x socks5h://127.0.0.1:1080 https://www.google.com
