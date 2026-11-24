#!/usr/bin/env python3
"""Tune installed monitoring packages; does not enable SQM or alter proxy rules.

Usage: ./tune_router_monitoring.py [--router root@192.168.5.1]
Requires collectd-mod-thermal, collectd-mod-conntrack, collectd-mod-uptime,
luci-app-statistics, nlbwmon and irqbalance. Uses persistent /overlay storage.
"""
import argparse
import re
import subprocess


SCRIPT = r'''set -eu
for service in luci_statistics collectd nlbwmon irqbalance; do
    test -x /etc/init.d/$service
done
for plugin in thermal conntrack uptime; do
    test -f /usr/lib/collectd/$plugin.so
done
backup=$(mktemp -d /root/monitoring-tuning.XXXXXX)
chmod 700 "$backup"
for config in luci_statistics nlbwmon irqbalance firewall; do
    cp -p /etc/config/$config "$backup/$config"
done
for path in /etc/sysctl.d/90-nlbwmon-buffer.conf /etc/init.d/nlbwmon-compat /usr/libexec/nlbwmon-compat; do
    if [ -f "$path" ]; then cp -p "$path" "$backup/$(echo "$path" | tr / _)"; fi
done
sysctl net.core.rmem_max >"$backup/rmem_max.txt"
echo "Backup: $backup"
wan=$(ubus call network.interface.wan status | jsonfilter -e '@.l3_device')
test -n "$wan"
uci set luci_statistics.collectd_interface.Interfaces="br-lan $wan"
uci set luci_statistics.collectd_thermal.enable=1
uci set luci_statistics.collectd_conntrack.enable=1
uci set luci_statistics.collectd_uptime.enable=1
uci set luci_statistics.collectd_rrdtool.DataDir=/tmp/rrd
uci set luci_statistics.collectd_rrdtool.backup=0
uci commit luci_statistics
mkdir -p /overlay/nlbwmon
chmod 700 /overlay/nlbwmon
uci set nlbwmon.@nlbwmon[0].database_directory=/overlay/nlbwmon
uci set nlbwmon.@nlbwmon[0].commit_interval=24h
uci set nlbwmon.@nlbwmon[0].netlink_buffer_size=1048576
uci -q delete nlbwmon.@nlbwmon[0].local_network || true
uci add_list nlbwmon.@nlbwmon[0].local_network=lan
uci commit nlbwmon
limit=$(cat /proc/sys/net/core/rmem_max)
if [ "$limit" -lt 1048576 ]; then limit=1048576; fi
echo "net.core.rmem_max=$limit" >/etc/sysctl.d/90-nlbwmon-buffer.conf
sysctl -p /etc/sysctl.d/90-nlbwmon-buffer.conf
uci set irqbalance.irqbalance.enabled=1
uci commit irqbalance

# ImmortalWrt issue #2496: fullcone probing can unregister netlink events,
# even when fullcone NAT is disabled. Limit the workaround to our tested kernel.
# Only the telemetry interface is reloaded, never nf_conntrack or NAT itself.
mkdir -p /usr/libexec
cat >/usr/libexec/nlbwmon-compat <<'COMPAT'
#!/bin/sh
[ "$(uname -r)" = 6.12.103 ] || exit 0
[ -d /sys/module/nft_fullcone ] || exit 0
rules=$(nft list ruleset 2>/dev/null) || exit 1
if printf '%s\n' "$rules" | grep -qw fullcone; then
    logger -t nlbwmon-compat 'Active fullcone rules: refusing notifier workaround'
    exit 0
fi
mkdir /tmp/nlbwmon-compat.lock 2>/dev/null || exit 0
trap 'rmdir /tmp/nlbwmon-compat.lock' EXIT
/etc/init.d/nlbwmon stop
if rmmod nf_conntrack_netlink; then
    modprobe nf_conntrack_netlink || {
        logger -t nlbwmon-compat 'Failed to reload netlink telemetry module'
        /etc/init.d/nlbwmon start
        exit 1
    }
else
    logger -t nlbwmon-compat 'Netlink telemetry module busy; left loaded'
fi
/etc/init.d/nlbwmon start
COMPAT
chmod 755 /usr/libexec/nlbwmon-compat
cat >/etc/init.d/nlbwmon-compat <<'INIT'
#!/bin/sh /etc/rc.common
START=99
start() {
    /usr/libexec/nlbwmon-compat
}
INIT
chmod 755 /etc/init.d/nlbwmon-compat
uci set firewall.nlbwmon_compat=include
uci set firewall.nlbwmon_compat.type=script
uci set firewall.nlbwmon_compat.path=/usr/libexec/nlbwmon-compat
uci set firewall.nlbwmon_compat.fw4_compatible=1
uci commit firewall
for service in luci_statistics collectd nlbwmon irqbalance nlbwmon-compat; do
    /etc/init.d/$service enable
done
/etc/init.d/luci_statistics restart
/etc/init.d/nlbwmon restart
/etc/init.d/irqbalance restart
# Check first: fw4's fullcone probe itself can break notifier registration.
fw4 check
/usr/libexec/nlbwmon-compat
echo 'Monitoring tuned. SQM and proxy configuration were not changed.'
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--router', default='root@192.168.5.1')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', a.router):
        p.error('Invalid SSH destination')
    subprocess.run(['ssh', a.router, 'sh -s'], input=SCRIPT, text=True, check=True)


if __name__ == '__main__':
    main()
