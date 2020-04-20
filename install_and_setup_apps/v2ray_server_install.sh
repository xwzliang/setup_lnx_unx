#!/usr/bin/env bash

# Time calibration
# Check time: date -R
cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime 

bash <(curl -L -s https://install.direct/go.sh)

systemctl start v2ray

## To only install this directly, use following:
# bash <(curl -L -s https://raw.githubusercontent.com/xwzliang/setup_lnx_unx/master/install_apps/v2ray_server_install.sh)
