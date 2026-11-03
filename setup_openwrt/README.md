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

## Subconverter Docker container

Run the local installer to reproduce the router's existing deployment:

```sh
./install_subconverter.sh
./install_subconverter.sh --router 192.168.8.1
```

Defaults, verified against the running router on 2026-11-03:

| Setting | Value |
| --- | --- |
| Image | `xwzliang/subconverter-custom:0.0.2` |
| Container name | `subconverter` |
| Published TCP port | `0.0.0.0:15051` → container `25500` |
| Persistent bind mount | `/etc/openclash/config` → `/data`, read/write |
| Restart policy | `always` |
| Network | Docker bridge |
| Health check | HTTP `/version` |

Docker must already be installed and running on the router, with `curl` available.
The installer pulls the image only if missing, creates the bind directory when
needed, starts the container, and waits for the service to respond. It uses SSH
without requiring SCP/SFTP. A matching running container is left alone; a stopped
matching container is started. A conflicting image, port, mount, restart policy,
privileged mode, or network causes an error without replacing the container or
its files. It does not reset additional configuration on an existing container.

Optional overrides:

```sh
./install_subconverter.sh --router 192.168.8.1 --ssh-port 2222 \
  --image xwzliang/subconverter-custom:0.0.2 \
  --name subconverter --port 15051 \
  --bind-address 192.168.8.1 --config-dir /etc/openclash/config
```

The default all-interface port binding reproduces the existing container. Use
`--bind-address` to bind only a specific router address. This installer does not
add WAN firewall permissions or modify OpenClash subscription settings. It also
does not install Docker itself. Install the container before the kill switch on
a new router so its `docker0` client interface can be discovered and protected.
For an already-installed kill switch, ensure `docker0` is in its protected
interface list; the current router already includes it.

The image contains its own defaults. Files bind-mounted from `/etc/openclash/config`
remain router-specific and are not copied from another router by this script.
A full setup on another supported router with Docker and OpenClash ready is:

```sh
./install_subconverter.sh --router 192.168.8.1
./install_openclash_killswitch.py --router 192.168.8.1
```

Non-network deployment tests:

```sh
python3 -m unittest discover -s . -p test_subconverter.py -v
```


## Named subscription conversion and installation

`install_openclash_subscription.py` reads `.env` next to the script (regardless
of your current working directory). It fetches each source URL with `User-Agent: Clash` and retries with
`Quantumultx` if the fetch fails, then passes the private downloaded file to the
router's subconverter to apply the template, validates the YAML and runs the installed
Clash core's configuration check, then installs the converted configs in OpenClash.
It needs Python 3.9+ and SSH locally, and the existing OpenClash, curl, Ruby, flock,
and subconverter deployment on the router. Run `./install_subconverter.sh` first
when setting up another router. No new Docker image is needed.

```sh
cd /Users/broliang/git/setup_lnx_unx/setup_openwrt
cp env.example .env
chmod 600 .env
# Edit .env: set your private URLs, identifiers, and ACTIVE_SUBSCRIPTION.
./install_openclash_subscription.py --name WGETCLOUD --check-only
./install_openclash_subscription.py --name WGETCLOUD
./install_openclash_subscription.py --all
# Multiple selected identifiers, or another router/env file:
./install_openclash_subscription.py --name WGETCLOUD SECONDARY
./install_openclash_subscription.py --env /path/to/router.env --router 192.168.8.1 --all
```

`SUBSCRIPTIONS` lists identifiers separated by spaces. `--name`, `--switch`, and
`ACTIVE_SUBSCRIPTION` match them case-insensitively; names must be unique ignoring
case. Keep the listed spelling in `SUB_<IDENTIFIER>_*` keys. Each needs
`SUB_<IDENTIFIER>_URL`; optional `SUB_<IDENTIFIER>_CONFIG` controls the LuCI name and
YAML filename (without `.yaml`). Config names must be unique. `TEMPLATE_URL` is the
shared conversion template; `SUB_<IDENTIFIER>_TEMPLATE` overrides it for one entry.
The example uses your existing custom template and preserves the
`wgetcloud_local_subconvert.yaml` name. Remove the example SECONDARY entry if you
only use one subscription. Values are literal, optionally quoted; shell commands,
variable expansion, multiline values, and inline comments are not supported.
The repository ignores `.env`; never commit private subscription URLs.

OpenClash runs **one** config at a time. If the selected identifiers include
`ACTIVE_SUBSCRIPTION`, that config is activated. Otherwise the running selection
is preserved; its core is restarted only if its own file was refreshed. `--all`
updates every listed entry and activates `ACTIVE_SUBSCRIPTION`; it does not merge
subscriptions. Other LuCI subscriptions and update schedules are preserved.
The old disabled `wgetcloud_update` entry and intermediate `wgetcloud_new.yaml`
are no longer needed by this flow and are left untouched. LuCI subscription
updates still use the saved remote URL and the local converter directly; they do
not use this installer's user-agent fallback. For providers that require it, run
this installer to refresh configs. Enable any provider download window immediately
before running it. The converter must have the default mount
`/etc/openclash/config:/data`; temporary raw files there are removed after conversion.

All selected conversions must pass before anything is replaced. Before installation,
the script creates a private `/root/openclash-subscription.XXXXXX` directory with:

- `backup/openclash`: previous `/etc/config/openclash` settings.
- `backup/etc/openclash/config/`: previous source YAML files.
- `backup/etc/openclash/backup/`: previous OpenClash backup YAML files.
- `manifest`: target paths, including files that did not previously exist.
- `worker.log`, validation logs, `phase`, and `result`: private diagnostics.

The directory is printed by the installer and retained after success. It contains
subscription credentials; keep it private and copy it off the router if desired.
Config replacements use a temporary file and rename. Installation/restart failures
restore the previous settings and files and attempt to restart the old config.
The router worker continues independently if SSH disconnects; inspect its `result`
file before retrying. This protects against command failures, not power loss or
storage failure midway through installation. Rollback cannot guarantee that an
already unhealthy core will start. The existing kill switch stays in place during
restarts, so an internet interruption is expected; local router access is retained.

`--check-only` fetches, converts and validates without changing subscriptions or
restarting OpenClash. A rejected/expired source URL or failed conversion leaves
all existing configs untouched. Logs remain private because converter/core errors
may contain credentials. No URLs are printed or passed in the SSH command line.

Tests: `python3 -m unittest test_subscription test_installer test_subconverter -v`.


### Switching the active subscription

```sh
# Activate an already installed config: no download and no subconverter call.
./install_openclash_subscription.py --switch MY_PROVIDER
# Fetch and convert fresh data first, then activate it (provider window applies).
./install_openclash_subscription.py --switch MY_PROVIDER --update
# Validate the saved config without switching or restarting.
./install_openclash_subscription.py --switch MY_PROVIDER --check-only
```

The identifier must appear in `SUBSCRIPTIONS`; its optional `CONFIG` value selects
which saved YAML to activate. Switching without `--update` does not require URL
or template values, a running subconverter, or an open provider download window.
The saved file must already exist and pass the Clash core's config check.
OpenClash restarts to activate it; the kill switch may briefly interrupt internet
access. The script backs up the previous UCI settings and restores them if
activation fails. Saved YAML files are not replaced in this mode.

`--switch` overrides `ACTIVE_SUBSCRIPTION` for this invocation and saves the active
selection on the router. It does not edit `.env`. Set `ACTIVE_SUBSCRIPTION` there
as well if you want subsequent `--all` updates to keep that selection. `--switch`
cannot be combined with `--name` or `--all`; `--update` requires `--switch`.


A provider that requires a specific client version can use a per-subscription
User-Agent. For example (match your identifier's spelling):

```dotenv
SUB_SHADOWSOCKS_USER_AGENT="Shadowrocket/2615 CFNetwork/3860.600.12 Darwin/25.5.0 iPhone16,2"
```

The installer tries this exact value first, followed by `Clash` and `Quantumultx`
if fetching fails. Without this option, the existing defaults remain unchanged.
