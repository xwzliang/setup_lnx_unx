#!/usr/bin/env python3
"""Install and select the Argon LuCI theme, backing up the current LuCI config.

Usage: ./install_luci_argon.py [--router root@192.168.5.1]
Uses normal SSH authentication and host-key verification. Supports apk and opkg.
Only the theme selection changes; network and OpenClash settings are untouched.
"""
import argparse
import re
import subprocess


SCRIPT = r'''set -eu
backup=$(mktemp -d /root/luci-theme-backup.XXXXXX)
chmod 700 "$backup"
cp -p /etc/config/luci "$backup/luci"
echo "LuCI configuration backup: $backup/luci"
if command -v apk >/dev/null 2>&1; then
    apk update
    apk add luci-theme-argon
elif command -v opkg >/dev/null 2>&1; then
    opkg update
    opkg install luci-theme-argon
else
    echo 'Neither apk nor opkg is available' >&2
    exit 1
fi
test -d /www/luci-static/argon
uci set luci.main.mediaurlbase=/luci-static/argon
uci commit luci
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.*
echo 'Argon selected. Refresh LuCI to see the theme.'
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--router', default='root@192.168.5.1')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', args.router):
        parser.error('Invalid SSH destination; use a hostname, IPv4 address, or SSH alias')
    subprocess.run(['ssh', args.router, 'sh -s'], input=SCRIPT, text=True, check=True)


if __name__ == '__main__':
    main()
