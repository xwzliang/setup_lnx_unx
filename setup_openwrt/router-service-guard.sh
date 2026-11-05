#!/bin/sh
# Restrict router-hosted management/proxy services before DNAT and proxy redirects.
# IPv4 and IPv6; preserves WireGuard's UDP listener and all client forwarding.
set -eu
CHAIN=SETUP_SERVICE_GUARD
for tool in iptables ip6tables; do
    command -v "$tool" >/dev/null || continue
    "$tool" -t mangle -L PREROUTING -n >/dev/null 2>&1 || continue
    "$tool" -t mangle -N "$CHAIN" 2>/dev/null || true
    "$tool" -t mangle -F "$CHAIN"
    # These interfaces are trusted router clients, not WAN ingress.
    for iface in lo br-lan wireguard docker0 utun; do
        "$tool" -t mangle -A "$CHAIN" -i "$iface" -j RETURN
    done
    # Only router-addressed service traffic. Ordinary forwarded replies are untouched.
    "$tool" -t mangle -A "$CHAIN" -m addrtype ! --dst-type LOCAL -j RETURN
    "$tool" -t mangle -A "$CHAIN" -p tcp -m multiport --dports 22,80,81,443,444,7681,7788,7789,7874,7890,7892,7893,7895,9090,15051 -j DROP
    "$tool" -t mangle -A "$CHAIN" -p tcp --dport 60000 -j DROP
    "$tool" -t mangle -A "$CHAIN" -p udp -m multiport --dports 7788,7789,7874,7892,7893,7895 -j DROP
    while "$tool" -t mangle -C PREROUTING -j "$CHAIN" 2>/dev/null; do
        "$tool" -t mangle -D PREROUTING -j "$CHAIN"
    done
    "$tool" -t mangle -I PREROUTING 1 -j "$CHAIN"
done
