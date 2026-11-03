# OpenClash persistent kill switch (legacy fw3 / TUN)

`openclash-killswitch.sh` runs **on the router as root**. It is deliberately
limited to OpenClash `fake-ip-tun`, the `utun` interface, policy table 354, and
OpenWrt/ImmortalWrt **fw3/iptables**. It refuses other configurations rather than
assuming that modern fw4/Mihomo has the same packet paths.

## Behavior

- Protected interfaces can reach connected local networks and the router itself.
- All other forwarded IPv4 traffic must enter OpenClash's TUN route. If that
  route disappears, an independent `prohibit` route prevents WAN fallback.
- OpenClash still decides whether to proxy or use `DIRECT`. The existing
  `GEOIP,CN` fallback is changed to `GEOIP,CN,DIRECT`, preserving earlier specific
  proxy rules. If absent, it is inserted before the final MATCH/FINAL rule.
- Mainland-China **firewall bypass** is disabled. China traffic goes through
  OpenClash's classifier and then directly to its destination.
- IPv6 is disabled in the kernel, on new interfaces, in DHCP/RA settings, and in
  OpenClash. IPv4 LAN management and IPv4 DHCP remain available.
- Software/hardware flow offloading is disabled. A mangle/FORWARD guard also
  blocks forwarded traffic exiting anywhere except trusted interfaces or utun.
- OpenClash stopping/restarting interrupts all protected clients' internet
  access. No separate service monitor is needed to detect the outage.

The policy-routing guard survives an OpenClash stop and a fw3 reload independently
of firewall chains. Its init script starts at S18 (before firewall/network on the
tested router), and interface hotplug plus a firewall include reapply it.

Router-originated traffic remains permitted for proxy connections, DNS, updates,
and recovery. This is **not** a router OUTPUT lockdown or a guarantee against a
client using another LAN device/router-local proxy as an alternate gateway. All
client ingress interfaces must be listed. Additional WANs, tunnels, firewall
packages, or changes to OpenClash's TUN/table behavior require revalidation.

## Install from your computer (recommended)

Run from an IPv4 LAN computer with Python **3.9+**, OpenSSH, and curl. OpenClash
must already be configured and working in the supported legacy fw3/TUN mode.
The installer uses normal SSH authentication and host-key verification; it does
not require SFTP or SCP support on the router.

```sh
# Default router: root@192.168.5.1
./install_openclash_killswitch.py

# Different router / SSH alias
./install_openclash_killswitch.py --router 192.168.8.1

# Explicit interfaces and a different SSH port
./install_openclash_killswitch.py --router 192.168.8.1 --port 2222 \
  --interfaces br-lan wireguard docker0
```

The script detects the devices in the `lan` and `docker` firewall zones (including
WireGuard when it belongs to `lan`). For additional/custom zones, it requires an
explicit `--interfaces` list rather than silently leaving clients unprotected.
List **all** trusted client ingress interfaces; do not include WAN.

The complete workflow is automatic:

1. Check IPv4 LAN SSH access and working external HTTPS endpoints.
2. Upload the sibling `openclash-killswitch.sh` and launch it in a detached
   router-local script, so SSH/internet interruptions do not terminate setup.
3. Wait for installation and verify policy routing, firewall guards, startup
   hooks, IPv6/offloading settings, the China DIRECT rule, router HTTP access,
   and external HTTPS access from the installing computer.
4. Download and validate a private backup under
   `~/.local/state/openclash-killswitch/<router-ip>/` (override with `--backup-dir`).
5. Confirm installation automatically, cancelling the router's rollback timer.

If installation, checks, or backup fail, it **does not confirm**. Once the router
installer has armed rollback, that timer remains independent of your computer.
The command exits nonzero and prints the remote installation-log location when
available. Verification can wait up to two minutes for OpenClash to become ready.
Run from the LAN without another VPN/proxy redirecting the computer's traffic;
the script disables HTTP proxy environment variables for its curl checks.

Running it again with an identical installed script verifies and backs up the
existing installation **without restarting OpenClash**. A different installed
version or interface list is refused rather than overwritten implicitly.
The wrapper does not automatically run the disruptive stop/recovery tests below;
those remain available as separate validation commands.

For local, non-network safety tests:

```sh
python3 -m unittest discover -s . -p test_installer.py -v
```

## Manual router-side installation

Inspect and back up your router before proceeding. Have IPv4 LAN SSH access; do
not perform this through an IPv6-only management connection. Allow time for a
brief internet interruption. Existing IPv6-only services become unavailable.

Copy the script without requiring an SFTP server:

```sh
ssh root@192.168.5.1 'umask 077; cat > /tmp/openclash-killswitch.sh' < openclash-killswitch.sh
ssh root@192.168.5.1 'sh /tmp/openclash-killswitch.sh install br-lan wireguard docker0'
```

Replace the example interface list with **all trusted client ingress interfaces**
on that router. Do not list a WAN interface. The installer verifies interfaces,
the proxy route, reserved tables 51820/51821 and policy-rule priorities
11000–11020. Existing earlier policy rules cause it to refuse installation.

The original config is backed up under
`/root/openclash-killswitch-backup-YYYYMMDD-HHMMSS/`. This contains a sysupgrade
backup, a targeted restoration archive, and diagnostic routing/firewall state.
Backups contain credentials: keep them private and **never commit them to Git**.

An independent router-local timer rolls back after **30 minutes** unless you
confirm. Verify from a LAN device before confirming:

```sh
ssh root@192.168.5.1 '/usr/sbin/openclash-killswitch status'
curl --noproxy '*' --max-time 10 https://example.com/
curl --noproxy '*' --max-time 10 https://www.baidu.com/
ssh root@192.168.5.1 '/usr/sbin/openclash-killswitch confirm'
```

`install` refuses to overwrite an existing installation. `apply` is idempotent;
it reasserts the installed guard without creating another backup or timer.

## Test outages without relying on internet access

The supplied controller runs from your computer and uses SSH to a Linux LAN
client with Python 3 and curl. It checks a working numeric-IP endpoint first,
stops the core with autonomous recovery armed, probes external and local access,
and waits for recovery. It deliberately interrupts internet access:

```sh
python3 test_outage.py --client server --client-ip 192.168.5.103
python3 test_outage.py --client server --client-ip 192.168.5.103 --reload-firewall
```

Use `--router` and `--router-ip` for a different router. The routing diagnostic
currently assumes the test client enters on `br-lan`; adapt it for other layouts.

Before stopping OpenClash, schedule recovery **on the router**, detached from
SSH. Example (router shell):

```sh
cat > /tmp/ks-recover.sh <<'EOF'
#!/bin/sh
sleep 35
/etc/init.d/openclash start
EOF
nohup sh /tmp/ks-recover.sh \
  >/root/openclash-killswitch-recovery.log 2>&1 </dev/null &
/etc/init.d/openclash stop
```

Use a **script file**, not `sh -c 'sleep ...; /etc/init.d/openclash ...'`:
the tested OpenClash stop routine kills processes whose command line contains
`/etc/init.d/openclash`, which kills that inline recovery command. The separate
script's command line contains only `/tmp/ks-recover.sh` and survives.

During the interval, a separate LAN device should fail both a domain request and
a known-working numeric-IP request, while IPv4 router SSH and its web server
remain reachable. Numeric-IP tests avoid confusing a DNS failure with a working
kill switch. Repeat after a firewall reload; inspect IPv6 state and test a
reboot when you have a suitable maintenance window. Do not assume a single
successful test establishes all future configurations are safe.

On the router, this lookup must return `Communication administratively
prohibited` while table 354 is absent, and `dev utun table 354` when active:

```sh
ip -4 route get 1.1.1.1 from CLIENT_LAN_IP iif br-lan
```

This lookup alone is not a substitute for actual client tests. `status` shows
the independent deny route, firewall counters, and every interface's IPv6 state.

## Restore

From IPv4 LAN SSH:

```sh
/usr/sbin/openclash-killswitch rollback
```

This restores the backed-up firewall/network/DHCP/OpenClash configuration and
overwrite hook, restarts services, restores prior runtime IPv6 flags, and removes
the installed guard. It retains the backup directory. Changes made to those
configuration files **after installation** will also be reverted, so take another
backup before rolling back much later.

The init service's `stop` intentionally does not remove protection. Removing the
guard requires the explicit `rollback` command. After upgrading OpenClash or
changing routing modes, retest or roll back and adapt the script first.

## Validation on 192.168.5.1 (2026-11-03)

Tested with OpenClash 0.45.141-beta, legacy Clash TUN, and fw3/iptables on
ImmortalWrt. Protected ingress: `br-lan`, `wireguard`, and `docker0`.

- A real LAN client (`192.168.5.103`) reached HTTPS before testing.
- With the core stopped, numeric-IP and domain HTTPS attempts failed; IPv4 LAN
  SSH and router HTTP remained reachable; the policy lookup returned a prohibit
  error. The detached recovery script restored connectivity automatically.
- Repeated the outage test with a firewall reload while the core was stopped:
  the same checks passed, including automatic recovery.
- Firewall reload with the core running preserved the guard and TUN route.
- Live OpenClash metadata for `www.baidu.com` showed `DIRECT`; the final config
  retained the earlier Claude rules and had `GEOIP,CN,DIRECT`.
- IPv6 was disabled on all current interfaces and the default for new interfaces;
  flow-offload rules were absent. Reapplying the guard was successful.
- The installation rollback timer was exercised during the initial test and
  successfully restored the original configuration. A subsequent installation
  was tested and explicitly confirmed.
- Startup ordering and the enabled S18 service were checked; **no router reboot
  was performed**, and no WAN packet capture was taken. These tests establish
  the tested packet paths, not correctness of future routing changes.

Backups remain private on the router and in the operator's local state directory;
no credentials, subscriptions, or backup archives belong in this repository.
