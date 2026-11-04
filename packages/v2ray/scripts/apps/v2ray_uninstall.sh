#!/usr/bin/env bash

systemctl stop v2ray
systemctl disable v2ray

rm -rf /etc/v2ray/*  #(config)
rm -rf /usr/bin/v2ray/*  #(bin)
rm -rf /var/log/v2ray/*  #(log)
rm -rf /lib/systemd/system/v2ray.service  #(systemd init)
rm -rf /etc/init.d/v2ray  #(sysv init)
