#!/usr/bin/env bash

ip="$1"
port="$2"
id="$3"

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

systemctl restart v2ray