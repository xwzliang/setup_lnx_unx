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

# Missing marker means enabled for installations made before toggles existed.
enabled() {
    case "$(cat "$BASE/enabled" 2>/dev/null || echo 1)" in
        1) return 0 ;;
        0) return 1 ;;
        *) fail "Invalid $BASE/enabled (expected 0 or 1)" ;;
    esac
}

set_enabled() {
    (umask 077; printf '%s\n' "$1" > "$BASE/enabled.new")
    mv "$BASE/enabled.new" "$BASE/enabled"
}

# Store only forwarding enable flags, keyed by zone pair rather than anonymous
# UCI section indexes. Never restore an old complete firewall configuration.
save_forwardings() (
    output=$1
    config_dir=${2:-}
    read_uci() {
        if test -n "$config_dir"; then uci -c "$config_dir" "$@"; else uci "$@"; fi
    }
    umask 077
    scratch=$(mktemp "$BASE/forwardings.XXXXXX")
    trap 'rm -f "$scratch"' 0
    for section in $(read_uci show firewall | sed -n 's/^firewall\.\([^=]*\)=forwarding$/\1/p'); do
        dest=$(read_uci -q get "firewall.$section.dest" || true)
        test "$dest" = wan || continue
        src=$(read_uci -q get "firewall.$section.src" || true)
        case "$src" in ''|*[!a-zA-Z0-9_-]*) fail "Unsupported forwarding source zone: $src";; esac
        if grep -q "^$src $dest " "$scratch"; then
            fail "Duplicate $src -> $dest forwarding grants; cannot safely toggle"
        fi
        value=$(read_uci -q get "firewall.$section.enabled" || echo __unset__)
        case "$value" in 0|1|true|false|yes|no|on|off|__unset__) :;; *) fail "Unsupported forwarding enabled value: $value";; esac
        printf '%s %s %s\n' "$src" "$dest" "$value" >> "$scratch"
    done
    mv "$scratch" "$output"
)

ensure_forwarding_baseline() (
    test ! -f "$BASE/forwarding-state" || exit 0
    # Upgrade a legacy installation from its original backup, without rolling
    # back later firewall/service/routing changes.
    backup=$(cat "$BASE/backup")
    test -f "$backup/restore.tar.gz" || fail "Original forwarding backup is missing"
    umask 077
    staging=$(mktemp -d "$BASE/legacy-firewall.XXXXXX")
    trap 'rm -rf "$staging"' 0
    tar -xzf "$backup/restore.tar.gz" -C "$staging" etc/config/firewall
    save_forwardings "$BASE/forwarding-state" "$staging/etc/config"
)

restore_forwardings() (
    # Validate all current zone pairs before making any UCI changes.
    umask 077
    current=$(mktemp "$BASE/current-forwardings.XXXXXX")
    trap 'rm -f "$current"' 0
    save_forwardings "$current"
    for section in $(uci show firewall | sed -n 's/^firewall\.\([^=]*\)=forwarding$/\1/p'); do
        dest=$(uci -q get "firewall.$section.dest" || true)
        test "$dest" = wan || continue
        src=$(uci -q get "firewall.$section.src")
        value=$(awk -v src="$src" -v dest="$dest" '$1 == src && $2 == dest {print $3}' "$BASE/forwarding-state")
        case "$value" in
            '') : ;; # A grant added after installation belongs to the user.
            __unset__) uci -q delete "firewall.$section.enabled" || true ;;
            *) uci set "firewall.$section.enabled=$value" ;;
        esac
    done
)

remove_guard() {
    for dev in $INTERFACES; do
        for pair in "11000 $LOCAL_TABLE" "11010 $PROXY_TABLE" "11020 $DENY_TABLE"; do
            set -- $pair
            while ip -4 rule del pref "$1" iif "$dev" lookup "$2" 2>/dev/null; do :; done
        done
        while iptables -w -t mangle -D FORWARD -i "$dev" -j OC_KS_FORWARD 2>/dev/null; do :; done
    done
    iptables -w -t mangle -F OC_KS_FORWARD 2>/dev/null || true
    iptables -w -t mangle -X OC_KS_FORWARD 2>/dev/null || true
    for table in "$LOCAL_TABLE" "$DENY_TABLE"; do
        # Linux may report a missing FIB table after the first successful off.
        if ip -4 route show table "$table" >/dev/null 2>&1; then
            ip -4 route flush table "$table"
        fi
    done
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
    disable_ipv6
    if ! enabled; then
        remove_guard
        exit 0
    fi
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

toggle() {
    test "$(id -u)" = 0 || fail "Run as root on the router"
    load
    mkdir -p /var/lock
    exec 8>/var/lock/openclash-killswitch-toggle.lock
    flock -x 8
    test ! -e "$BASE/pending" || fail "Confirm the pending installation before toggling"
    test -z "$(uci changes)" || fail "Commit or revert pending UCI changes before toggling"
    case "$1" in
        on)
            if ! enabled; then save_forwardings "$BASE/forwarding-state"; else ensure_forwarding_baseline; fi
            set_enabled 1
            # Establish protection before changing forwarding or reloading fw3.
            apply
            uci set firewall.@defaults[0].flow_offloading=0
            uci set firewall.@defaults[0].flow_offloading_hw=0
            uci set firewall.@defaults[0].forward=REJECT
            for section in $(uci show firewall | sed -n 's/^firewall\.\([^=]*\)=forwarding$/\1/p'); do
                if test "$(uci -q get "firewall.$section.dest" || true)" = wan; then
                    uci set "firewall.$section.enabled=0"
                fi
            done
            uci commit firewall
            ;;
        off)
            if enabled; then
                ensure_forwarding_baseline
                restore_forwardings
                uci commit firewall
            fi
            set_enabled 0
            ;;
    esac
    # Do not hold apply's lock over reload: fw3 invokes the same apply hook.
    /etc/init.d/firewall reload
    apply
    echo "Kill switch $1 (IPv6 remains disabled)."
}

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
    remove_guard
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
    save_forwardings "$BASE/forwarding-state"
    set_enabled 1
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
# Retain the selected mode on service stop. Use explicit on/off to change it.
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
    on|enable) toggle on ;;
    off|disable) toggle off ;;
    state) load; if enabled; then echo on; else echo off; fi ;;
    confirm) load; rm -f "$BASE/pending"; echo 'Confirmed; automatic rollback cancelled.' ;;
    rollback) rollback ;;
    status)
        load
        if enabled; then echo 'Kill switch: on'; else echo 'Kill switch: off'; fi
        echo "Protected interfaces: $INTERFACES"
        echo "Backup: $(cat "$BASE/backup")"
        test ! -e "$BASE/pending" || echo 'AUTO-ROLLBACK PENDING'
        ip -4 rule show
        ip -4 route show table "$LOCAL_TABLE"
        ip -4 route show table "$PROXY_TABLE"
        ip -4 route show table "$DENY_TABLE"
        iptables -t mangle -nvL OC_KS_FORWARD 2>/dev/null || true
        for p in /proc/sys/net/ipv6/conf/*/disable_ipv6; do echo "$p=$(cat "$p")"; done
        ;;
    *) echo "Usage: $0 {install INTERFACE...|on|off|apply|state|status|confirm|rollback}"; exit 2 ;;
esac
