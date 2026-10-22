#!/usr/bin/env bash

# Do nothing when closing the lid of the laptop

logind_conf=/etc/systemd/logind.conf
# Remove line start with HandleLidSwitch and append HandleLidSwitch=ignore to the end of the /etc/systemd/logind.conf
sed -i '/^HandleLidSwitch/d' $logind_conf
echo HandleLidSwitch=ignore >> $logind_conf
service systemd-logind restart
echo Change settings: Do nothing when closing the lid of the laptop: succeed.
