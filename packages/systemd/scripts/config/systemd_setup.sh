#!/usr/bin/env bash
set -euo pipefail
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\n' | sudo tee /etc/systemd/logind.conf.d/90-setup-lid.conf >/dev/null
echo 'Lid behavior configured. It takes effect after restarting systemd-logind or rebooting.'
