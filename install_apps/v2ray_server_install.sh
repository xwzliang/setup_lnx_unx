#!/usr/bin/env bash

# Time calibration
# Check time: date -R
cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime 

bash <(curl -L -s https://install.direct/go.sh)

systemctl start v2ray
