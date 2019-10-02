#!/usr/bin/env bash

echo 'forward-socks5 / 127.0.0.1:1080 .' >>/etc/privoxy/config

systemctl start privoxy.service
systemctl -l status privoxy.service
