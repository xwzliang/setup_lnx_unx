#!/bin/sh
# Persistent fail-closed LAN routing for legacy OpenClash TUN + fw3.
set -eu
BASE=/etc/openclash-killswitch
SELF=/usr/sbin/openclash-killswitch
LOCAL_TABLE=51820
DENY_TABLE=51821
PROXY_TABLE=354
fail() { echo "ERROR: $*" >&2; exit 1; }

load() {
    test -f "$BASE/interfaces" || fail "Not installed"
    INTERFACES=$(cat "$BASE/interfaces")
}

disable_ipv6() {
    for p in /proc/sys/net/ipv6/conf/*/disable_ipv6; do
        test ! -f "$p" || echo 1 > "$p"
    done
}

apply() (
    load
    mkdir -p /var/lock
    exec 9>/var/lock/openclash-killswitch.lock
    flock -x 9
    # Install the final deny BEFORE allowing any paths. Never flush these rules.
    ip -4 route replace prohibit default table "$DENY_TABLE"
    for dev in $INTERFACES; do
        if ! ip -4 rule show | grep -F "iif $dev lookup $DENY_TABLE" >/dev/null; then
            ip -4 rule add pref 11020 iif "$dev" lookup "$DENY_TABLE"
        fi
    done
    for dev in $INTERFACES; do
        # Only connected LAN routes are exempt, never the WAN default route.
        if ip link show dev "$dev" >/dev/null 2>&1; then
            ip -4 route show table main dev "$dev" scope link |
            while read -r prefix rest; do
                case "$prefix" in default|broadcast|local|unreachable|prohibit|blackhole|'') continue;; esac
                ip -4 route replace table "$LOCAL_TABLE" "$prefix" dev "$dev" scope link
            done
        fi
    done
    for dev in $INTERFACES; do
        if ! ip -4 rule show | grep -F "iif $dev lookup $LOCAL_TABLE" >/dev/null; then
            ip -4 rule add pref 11000 iif "$dev" lookup "$LOCAL_TABLE"
        fi
        if ! ip -4 rule show | grep -F "iif $dev lookup $PROXY_TABLE" >/dev/null; then
            ip -4 rule add pref 11010 iif "$dev" lookup "$PROXY_TABLE"
        fi
    done
    disable_ipv6
    # Defense in depth before established/related and Docker ACCEPT rules.
    # The routing deny above remains in place even during fw3 table rebuilds.
    iptables -w -t mangle -N OC_KS_FORWARD 2>/dev/null || true
    if ! iptables -w -t mangle -S OC_KS_FORWARD | grep -- '-j DROP' >/dev/null; then
        for dev in $INTERFACES utun; do
            iptables -w -t mangle -A OC_KS_FORWARD -o "$dev" -j RETURN
        done
        iptables -w -t mangle -A OC_KS_FORWARD -j DROP
    fi
    for dev in $INTERFACES; do
        iptables -w -t mangle -C FORWARD -i "$dev" -j OC_KS_FORWARD 2>/dev/null ||
            iptables -w -t mangle -I FORWARD 1 -i "$dev" -j OC_KS_FORWARD
    done
)

rollback() {
    load
    backup=$(cat "$BASE/backup")
    # Restore files first. Retain the guard until original services recover.
    rm -f "$BASE/pending"
    /etc/init.d/openclash-killswitch disable
    tar -xzf "$backup/restore.tar.gz" -C /
    while read -r path; do rm -f "/$path"; done < "$backup/absent"
    while read -r path value; do
        test ! -f "$path" || echo "$value" > "$path"
    done < "$backup/ipv6-runtime"
    /etc/init.d/odhcpd restart || true
    /etc/init.d/dnsmasq restart
    /etc/init.d/firewall restart
    /etc/init.d/openclash restart
    for dev in $INTERFACES; do
        for pair in "11000 $LOCAL_TABLE" "11010 $PROXY_TABLE" "11020 $DENY_TABLE"; do
            set -- $pair
            while ip -4 rule del pref "$1" iif "$dev" lookup "$2" 2>/dev/null; do :; done
        done
        while iptables -w -t mangle -D FORWARD -i "$dev" -j OC_KS_FORWARD 2>/dev/null; do :; done
    done
    iptables -w -t mangle -F OC_KS_FORWARD 2>/dev/null || true
    iptables -w -t mangle -X OC_KS_FORWARD 2>/dev/null || true
    ip -4 route flush table "$LOCAL_TABLE"
    ip -4 route flush table "$DENY_TABLE"
    rm -rf "$BASE"
    echo "Restored original configuration from $backup"
}

install() {
    test "$(id -u)" = 0 || fail "Run as root on the router"
    test "$#" -gt 0 || fail "Specify all trusted ingress interfaces, e.g. install br-lan wireguard docker0"
    test ! -e "$BASE" || fail "Already installed; use apply/status or rollback first"
    test -z "$(uci changes)" || fail "Commit or revert pending UCI changes before installation"
    command -v fw3 >/dev/null || fail "Only fw3/iptables is supported; fw4 needs a separate implementation"
    for cmd in ip iptables ruby sysupgrade nohup flock; do command -v "$cmd" >/dev/null || fail "Missing $cmd"; done
    test "$(uci -q get openclash.config.en_mode)" = fake-ip-tun || fail "Requires OpenClash fake-ip-tun mode"
    ip -4 route show table "$PROXY_TABLE" | grep -Eq '^default dev utun scope link[[:space:]]*$' || fail "Expected table 354 default dev utun"
    test -z "$(ip -4 route show table "$LOCAL_TABLE" 2>/dev/null)" || fail "Table $LOCAL_TABLE already used"
    test -z "$(ip -4 route show table "$DENY_TABLE" 2>/dev/null)" || fail "Table $DENY_TABLE already used"
    # OpenClash lets the kernel choose its fwmark rule priority. After a restart
    # it can be 10999 rather than 32765; that known proxy rule is compatible.
    ip -4 rule show | awk -F: '$1 > 0 && $1 <= 11020 && $0 !~ /fwmark 0x162 lookup 354/ {bad=1} END {exit bad}' || fail "Conflicting early policy rules"
    for dev in "$@"; do
        case "$dev" in *[!a-zA-Z0-9_.-]*|'') fail "Invalid interface $dev";; esac
        ip link show dev "$dev" >/dev/null || fail "Interface $dev does not exist"
        ip -4 route show default | grep -q "dev $dev " && fail "Refusing WAN interface $dev"
    done
    umask 077
    backup="/root/openclash-killswitch-backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$backup" "$BASE"
    sysupgrade -b "$backup/sysupgrade.tar.gz"
    paths='etc/config/firewall etc/config/network etc/config/dhcp etc/config/openclash etc/openclash/custom/openclash_custom_overwrite.sh etc/sysctl.d/90-openclash-killswitch.conf etc/init.d/openclash-killswitch etc/hotplug.d/iface/99-openclash-killswitch usr/sbin/openclash-killswitch'
    : > "$backup/present"; : > "$backup/absent"
    for path in $paths; do
        if test -e "/$path"; then echo "$path" >> "$backup/present"; else echo "$path" >> "$backup/absent"; fi
    done
    tar -czf "$backup/restore.tar.gz" -C / -T "$backup/present"
    for p in /proc/sys/net/ipv6/conf/*/disable_ipv6; do echo "$p $(cat "$p")"; done > "$backup/ipv6-runtime"
    iptables-save > "$backup/iptables.txt"
    ip -4 rule show > "$backup/ip-rules.txt"
    ip -4 route show table all > "$backup/ip-routes.txt"
    printf '%s\n' "$@" > "$BASE/interfaces"
    echo "$backup" > "$BASE/backup"
    cp "$0" "$SELF"; chmod 700 "$SELF"
    # Recovery is router-local and does not depend on internet or this SSH session.
    echo "$backup" > "$BASE/pending"
    # Bind the timer to this installation, so an older confirmed timer cannot
    # roll back a subsequent installation.
    nohup sh -c 'sleep 1800; test "$(cat /etc/openclash-killswitch/pending 2>/dev/null)" != "$1" || /usr/sbin/openclash-killswitch rollback' ks-watchdog "$backup" > "$backup/rollback.log" 2>&1 < /dev/null &
    echo "$!" > "$BASE/watchdog-pid"

    cat > /etc/init.d/openclash-killswitch <<'INIT'
#!/bin/sh /etc/rc.common
START=18
STOP=99
start() { /usr/sbin/openclash-killswitch apply; }
reload() { start; }
# Deliberately retain protection on service stop. Use explicit rollback to remove.
stop() { :; }
INIT
    chmod 755 /etc/init.d/openclash-killswitch
    cat > /etc/hotplug.d/iface/99-openclash-killswitch <<'HOTPLUG'
#!/bin/sh
case "$ACTION" in ifup|ifupdate) /usr/sbin/openclash-killswitch apply ;; esac
HOTPLUG
    chmod 755 /etc/hotplug.d/iface/99-openclash-killswitch
    cat > /etc/sysctl.d/90-openclash-killswitch.conf <<'SYSCTL'
net.ipv6.conf.all.disable_ipv6=1
net.ipv6.conf.default.disable_ipv6=1
SYSCTL
    /etc/init.d/openclash-killswitch enable
    # Preserve the user's existing overwrite hook, including an existing exit.
    if test -f /etc/openclash/custom/openclash_custom_overwrite.sh; then
        cp /etc/openclash/custom/openclash_custom_overwrite.sh "$BASE/previous-overwrite.sh"
        chmod 700 "$BASE/previous-overwrite.sh"
    fi
    cat > /etc/openclash/custom/openclash_custom_overwrite.sh <<'OVERWRITE'
#!/bin/sh
set -e
if test -f /etc/openclash-killswitch/previous-overwrite.sh; then
    /etc/openclash-killswitch/previous-overwrite.sh "$@"
fi
# Keep specific rules ahead of the CN fallback. Always direct CN via the core.
ruby -ryaml -e '
  p = ARGV.fetch(0); c = YAML.load_file(p); r = c.fetch("rules")
  found = false
  r.map! { |x| if x.start_with?("GEOIP,CN,"); found = true; "GEOIP,CN,DIRECT"; else x; end }
  unless found
    i = r.index { |x| x.start_with?("MATCH,", "FINAL,") } || r.length
    r.insert(i, "GEOIP,CN,DIRECT")
  end
  c["ipv6"] = false
  c["dns"]["ipv6"] = false if c["dns"].is_a?(Hash)
  File.write(p, YAML.dump(c))
' "$1"
OVERWRITE
    chmod 755 /etc/openclash/custom/openclash_custom_overwrite.sh
    uci set firewall.@defaults[0].flow_offloading=0
    uci set firewall.@defaults[0].flow_offloading_hw=0
    uci set firewall.@defaults[0].forward=REJECT
    # Retain LAN INPUT/OUTPUT and local forwarding. Disable every WAN forwarding grant.
    for section in $(uci show firewall | sed -n 's/^firewall\.\([^=]*\)=forwarding$/\1/p'); do
        if test "$(uci -q get "firewall.$section.dest")" = wan; then
            uci set "firewall.$section.enabled=0"
        fi
    done
    uci set firewall.openclash_killswitch=include
    uci set firewall.openclash_killswitch.type=script
    uci set firewall.openclash_killswitch.path="$BASE/firewall-include.sh"
    uci set firewall.openclash_killswitch.reload=1
    printf '#!/bin/sh\n/usr/sbin/openclash-killswitch apply\n' > "$BASE/firewall-include.sh"
    chmod 700 "$BASE/firewall-include.sh"
    for section in $(uci show network | sed -n 's/^network\.\([^=]*\)=interface$/\1/p'); do
        uci set "network.$section.ipv6=0"
        uci -q delete "network.$section.ip6assign" || true
        if test "$(uci -q get "network.$section.proto")" = dhcpv6; then
            uci set "network.$section.auto=0"
            ifdown "$section" || true
        fi
    done
    for section in $(uci show dhcp | sed -n 's/^dhcp\.\([^=]*\)=dhcp$/\1/p'); do
        uci set "dhcp.$section.ra=disabled"
        uci set "dhcp.$section.dhcpv6=disabled"
        uci set "dhcp.$section.ndp=disabled"
    done
    uci set openclash.config.china_ip_route=0
    uci set openclash.config.china_ip6_route=0
    uci set openclash.config.ipv6_enable=0
    uci set openclash.config.ipv6_dns=0
    for package in firewall network dhcp openclash; do uci commit "$package"; done
    apply
    /etc/init.d/odhcpd restart
    /etc/init.d/firewall restart
    /etc/init.d/openclash restart
    echo "Installed. Backup: $backup"
    echo "AUTO-ROLLBACK in 1800 seconds unless: $SELF confirm"
}

case "${1:-}" in
    install) shift; install "$@" ;;
    apply) apply ;;
    confirm) load; rm -f "$BASE/pending"; echo 'Confirmed; automatic rollback cancelled.' ;;
    rollback) rollback ;;
    status)
        load
        echo "Protected interfaces: $INTERFACES"
        echo "Backup: $(cat "$BASE/backup")"
        test ! -e "$BASE/pending" || echo 'AUTO-ROLLBACK PENDING'
        ip -4 rule show
        ip -4 route show table "$LOCAL_TABLE"
        ip -4 route show table "$PROXY_TABLE"
        ip -4 route show table "$DENY_TABLE"
        iptables -t mangle -nvL OC_KS_FORWARD
        for p in /proc/sys/net/ipv6/conf/*/disable_ipv6; do echo "$p=$(cat "$p")"; done
        ;;
    *) echo "Usage: $0 {install INTERFACE...|apply|status|confirm|rollback}"; exit 2 ;;
esac
