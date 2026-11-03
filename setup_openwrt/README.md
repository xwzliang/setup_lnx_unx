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


`worker.log` includes timestamped stages, conversion HTTP status and output size,
the installed core version, complete core validation output, backup location, and
restart/rollback outcomes. Validation output is also retained in `validation-*.log`;
restart failures include `restart.log` output. These logs stay in the private router
directory and may contain sensitive config details; the local CLI prints only
progress and log paths. An unsupported protocol error is a core compatibility
failure, even when fetching and conversion both succeeded.


## Upgrade legacy OpenClash to Mihomo

`install_mihomo.py` upgrades the core while preserving the current active subscription.
It supports the legacy fw3/OpenClash layout used here, with this directory's kill
switch already installed, an existing `core/clash_meta`, persistent core storage,
and a test machine on `br-lan` (the local machine by default). It currently supports router SSH port 22.
Run from the router's LAN. Do not edit router config concurrently with the upgrade.

```sh
# Default: use this machine and detect its LAN IP from the router SSH connection.
./install_mihomo.py
./install_mihomo.py --router 192.168.8.1
# Optional: use a separate Linux LAN client.
./install_mihomo.py --router 192.168.5.1 --client server --client-ip 192.168.5.103
# Optional: validate another router-side YAML before changing anything.
./install_mihomo.py --client server --client-ip 192.168.5.103 \
  --validate-config /etc/openclash/config/another.yaml
```

Without `--client`, curl probes run locally (macOS/Linux), bound to the IPv4
address observed by the router in `SSH_CONNECTION`. No SSH server is needed on
the local machine. The router must reach it through `br-lan`; run directly from
that LAN, not through a jump host, VPN, or a public SSH forwarding endpoint.

`--client` is a local SSH alias/address for a Linux machine behind the target
router, with curl available; `--client-ip` is that machine's LAN IPv4 address.
Both options are required only when selecting a separate client. Use values
appropriate to each router. The script intentionally stops OpenClash
and reloads the firewall to test fail-closed behavior. A file-based recovery job
on the router starts OpenClash again after 25 seconds, independently of SSH.
Local router HTTP and SSH must remain accessible throughout.

The installer defaults to pinned official Mihomo **v1.19.33** and verifies SHA-256
before upload. Choose a release explicitly or resolve the latest stable release:

```sh
./install_mihomo.py --version 1.19.33
./install_mihomo.py --version v1.19.33
./install_mihomo.py --version latest
```

`latest` is resolved once using the official GitHub Releases API, then that concrete
version is used for download and running-core verification. Non-default releases
use the asset's published SHA-256 digest. Older assets without a digest require
`--sha256 <trusted-sha256>`; verification is never silently skipped. A supplied
checksum must agree with the published/pinned checksum when one is available.
The selected version, URL and hash are retained in the router's `release.txt`.
The default pinned release still works without an API lookup, including when
`--archive` supplies its download locally. Other versions need API access even
with `--archive`, to resolve and verify the selected asset. New/older releases
still must pass config and live-routing checks; version selection does not imply
compatibility with every OpenClash version.
It selects `amd64-compatible` on x86-64 or `arm64` on aarch64; other architectures
are rejected. `--archive /path/to/official.gz` avoids downloading again but still
requires the checksum for the selected version. Checksum values come from the official GitHub release.
Before writing the upload, it estimates free space needed for the binary and two
compressed backups, plus a reserve; insufficient space aborts without mutation.
Old upgrade directories can be sizable: archive them privately before removing
any, and retain the backup needed for rollback.

Before activation, it backs up `/etc/openclash` (including both old cores), UCI
OpenClash settings, and `/etc/init.d/openclash`. The full backup also includes
network/firewall/DHCP settings and the kill-switch configuration. Both the active
source and generated runtime configs must pass the new core's validation.

For this older OpenClash release, the installer adds a narrowly scoped
`SAFE_PATHS=/usr/share/openclash/ui` export to its init script, allowing Mihomo to
serve the existing dashboard. OpenClash package upgrades may replace this init
script; review that integration when upgrading OpenClash itself. Meta TUN retains
OpenClash's `utun` interface and route table 354; automatic route generation remains
under OpenClash's existing configuration.

It enables the Meta core, restarts, checks routing, IPv6 disablement and the firewall
guard, probes public and mainland-China sites, then runs `test_outage.py` with
`--reload-firewall`. A separate router watchdog restores the old core/config after
15 minutes unless verification completes and confirmation is recorded. Errors after
mutation request immediate restoration. Do not power off the router during the
transaction; the watchdog is process-based and does not survive a reboot.

Private router artifacts are in `/root/mihomo-upgrade.XXXXXX`; successful runs
also copy `full-backup.tar.gz` to
`~/.local/state/mihomo-upgrade/<router-ip>/mihomo-upgrade.XXXXXX.tar.gz` (mode 600).
The installer prints a detached manual rollback command. Rollback restores
OpenClash-owned files and reapplies the existing kill switch; network/firewall/DHCP
snapshots are reference backups, not automatically restored over unrelated changes.
Rollback returns to the active config/settings from upgrade time.

Tests: `python3 -m unittest test_mihomo -v` covers preflight rejection and executable
upgrade/rollback transactions with simulated router tools. Live verification on the
router additionally confirmed stopped-core blocking, firewall-reload persistence,
local management access, automatic recovery, and AnyTLS config validation.

## Manage OpenClash priority custom rules

Edit `openclash_custom_rules.yaml` in this folder. It was initialized from the
router's existing priority custom-rules field, preserving all rules and comments.
Use a YAML list, matching the LuCI editor; earlier rules take priority:

```yaml
- DOMAIN-KEYWORD,lovart,新加坡
- DOMAIN-KEYWORD,claude,新加坡
```

Apply from any working directory (the default file is next to the script):

```sh
./update_openclash_rules.py --check-only
./update_openclash_rules.py
./update_openclash_rules.py --router 192.168.8.1 --file /path/to/rules.yaml
```

This replaces `/etc/openclash/custom/openclash_custom_rules.list`, the **priority**
`*自定义规则` field under 覆写设置 → 规则设置. It enables custom rules and restarts
OpenClash to apply them; it does not replace the separate extended-rules field.
The local file is the source of truth: edits made in LuCI are overwritten by the
next sync unless copied back locally. Use `[]` to explicitly clear the list.
Rules' target proxy/group names must exist in the currently active subscription.

The updater validates YAML and checks a candidate config with the installed core
before changing anything. It saves previous rules and OpenClash UCI settings under
`/root/openclash-rules.XXXXXX/backup`, then atomically replaces the rule file.
Restart/verification failures restore the old rules/settings and attempt to restart
the previous configuration. A detached worker survives loss of SSH; inspect its
`result` and private `worker.log` before retrying. As with the subscription updater,
this command-level rollback does not cover power loss or disk failure.
If the same rules are already stored, enabled and present in the generated runtime
config, the updater skips the restart. `--check-only` never saves or restarts.

A changed ruleset briefly interrupts internet access while OpenClash restarts;
the existing kill switch remains installed. No subscription download or subconverter
request is needed. You can refresh the LuCI page after syncing to see the new text.
Tests: `python3 -m unittest test_rules -v` (requires Ruby for YAML parsing).

## Split DNS and default-to-proxy routing

Requires an already working Mihomo core, installed kill switch, TUN/fake-IP mode,
Ruby, and `/etc/openclash/GeoSite.dat` containing `cn`. Run from a LAN client:

```sh
./install_openclash_split_dns.py --check-only
./install_openclash_split_dns.py
./install_openclash_split_dns.py --router 192.168.8.1 --proxy-group '新加坡'
```

The proxy group must exist in every subscription you activate and contain only
explicit proxy nodes/groups, with no DIRECT/PASS options or provider-based dynamic
membership. The default is `新加坡`. Preflight rejects unsafe or missing groups.

Policy, applied after the existing overwrite hook on each config regeneration:

- Preserve explicit custom and subscription rules, including foreign services
  intentionally routed DIRECT. Existing rule priority is retained.
- Replace the broad `GEOIP,CN` rule with `GEOSITE,cn,DIRECT`, using the installed
  mainland-domain dataset. An unknown domain does not become DIRECT merely because
  its IP is Chinese. Existing explicit IP exceptions remain, with `no-resolve` so
  they cannot trigger DNS lookups before a domain-routing decision.
- Replace MATCH/FINAL with the specified proxy-only group.
- Default real DNS lookups use `https://1.1.1.1/dns-query` **through that group**.
  This DNS group is fixed even when a destination's explicit rule chooses another
  region. Proxy protocols may also resolve destination domains on the proxy server.
- DIRECT connections use `https://223.5.5.5/dns-query` directly, for domestic CDN
  selection. This includes intentional foreign DIRECT exceptions.
- Proxy-node hostname bootstrap uses that domestic encrypted resolver directly.
  Resolver endpoints use literal IPs, avoiding an extra plaintext bootstrap lookup.
- Replace inherited DNS policy/fallback entries so they cannot bypass this default.
  Keep fake-IP exclusions for compatibility: an excluded domain's initial lookup
  uses the proxied resolver; a DIRECT connection is then re-resolved domestically.
  Such exclusions can therefore depend on a working proxy. Fake-IP A/AAAA responses
  otherwise avoid upstream lookups until a connection needs them. Other query types
  use the proxied default; this is not an all-query domestic DNS allowlist.
- Preserve the forwarding kill switch and disabled IPv6. If OpenClash is stopped,
  mainland access is blocked too. Direct DoH still reveals the router's public IP
  and queried names to the domestic resolver; it encrypts them against transit ISPs.

The script disables OpenClash's separate dnsmasq custom-domain upstream feature.
It does not control an application's own DoH settings or independently configured
DNS daemons. A selected group's failure cannot fall back to a direct default DNS
connection. Explicit DIRECT subscription rules remain intentional exceptions.

Files on the router are `/etc/openclash/split-dns/{split_dns.rb,settings.yaml,previous-overwrite.sh}`
and the custom overwrite wrapper. Install the kill switch **before** this feature.
Run this installer again to change the proxy group or update the transform.
Subscription regeneration and custom-rule updates reapply the policy automatically.
If the transform encounters an invalid group, it writes a reject-all candidate
because older OpenClash versions ignore hook exit status.

Each run saves the previous hook, policy, generated config and OpenClash settings
under `/root/openclash-split-dns.XXXXXX/backup`; `config-backup.tar.gz` also snapshots
network, DHCP, firewall and custom settings. A checksum-verified copy is saved to
`~/.local/state/openclash-split-dns/<router-ip>/` with mode 600. A detached worker and ten-minute
router-local watchdog restore unconfirmed changes. Validation checks both the
candidate and regenerated runtime, forwarding protection, IPv6, and LAN-client
access to Baidu, example.com and the router. No Claude/Anthropic test requests are
made. Keep the router powered on until installation completes; the watchdog does
not survive a reboot. The printed rollback command restores the old OpenClash
files and reapplies the guard without overwriting later network/firewall changes.
Private logs may include subscription secrets; do not publish them.

For a disruptive stopped-core check with automatic recovery:

```sh
./test_outage.py --reload-firewall
```

Tests: `python3 -m unittest test_split_dns test_installer test_mihomo test_rules`.

### Apps with cached IPs or their own DNS

The split-DNS hook enables HTTP/TLS/QUIC hostname sniffing for domain-based routing
of connections that arrive without a DNS hostname. It uses visible HTTP Host / TLS
SNI / QUIC handshake information; it does not decrypt HTTPS application content.
`override-destination: false` preserves the destination IP chosen by the app.
HTTP ports 80/8080 and TLS/QUIC ports 443/8443 are included, and existing sniffing
ports and exclusions are preserved. Existing domain rules still decide DIRECT vs
proxy; unidentifiable traffic retains the proxy fallback. This cannot classify
traffic without an exposed hostname, including some encrypted-client-hello flows.
Rerun the installer to apply this improvement, with a fresh backup and verification.

## Identify IoT hardware, reserve DHCP addresses, and allow mainland IPs

Run on the router's LAN, with SSH access to both the router and Home Assistant:

```sh
./discover_iot.py --router 192.168.5.1 --ha ha --refresh-cloud
./install_openclash_split_dns.py --iot-inventory iot_devices.json --check-only
./install_openclash_split_dns.py --iot-inventory iot_devices.json
```

Discovery reads Home Assistant's Xiaomi integration cache and, with
`--refresh-cloud`, reads the current Xiaomi inventory using that integration's
existing authentication **on the HA host**. Authentication is sent only to Xiaomi;
credentials, tokens, nested device records and Wi-Fi configuration are not exported.
The SSH account needs read access to `/config/.storage` and the installed Xiaomi
integration. This is currently Xiaomi-specific; SwitchBot or other integrations
are not automatically included. No appliances are switched or actuated.

The tool sends a read-only miIO hello to DHCP clients and matches returned device
IDs to the inventory. Where a Wi-Fi device does not answer hello, an exact cloud
MAC-to-active-DHCP-MAC match is accepted. A hostname or manufacturer guess alone is
never enough. Network routers are excluded. The output `iot_devices.json` is mode
600 and Git-ignored; it contains names, models, rooms, MACs, current IPs and evidence.
Review it before applying, especially after changing homes/accounts. Each discovery
replaces that file with the devices currently identified. Devices that are offline
or cannot be matched remain listed as unresolved and receive no new exception.

Bluetooth/mesh sensors and IR virtual appliances do not receive DHCP reservations.
IR `parent_id` mappings identify their controlling speaker's IP. Bluetooth gateway
associations missing from the API are reported as unknown, not inferred from room
names. Reserve the actual central gateway/speakers instead. Home Assistant itself,
phones and computers are not automatically placed in the IoT list.

The installer keeps current IPs and adds `dhcp` host sections named `iot_<MAC>`.
It validates subnet membership, duplicate IPs/MACs, live lease conflicts, existing
reservations and uncommitted DHCP changes **before any reservation is written**.
Matching existing reservations are preserved; conflicting ones abort installation.
It restarts dnsmasq and OpenClash but does not force devices to reconnect or move IPs.
DHCP config is included in both immediate rollback and the router-local watchdog.

For each reserved IP, the generated rule is equivalent to:

```yaml
- AND,((SRC-IP-CIDR,192.168.5.135/32),(GEOIP,CN,no-resolve)),DIRECT
```

These rules follow all existing explicit subscription/custom rules and the known
mainland-domain rule, immediately before MATCH. They only allow direct connections
for a listed source **and an already-known mainland destination IP**; they do not
resolve unknown domains domestically or make every IoT destination DIRECT. Other
clients keep the proxy fallback. The forwarding kill switch remains active, so
OpenClash stopping still blocks these devices' internet access. Resolver failures
or foreign cloud endpoints can still cause device outages; this is not an
unconditional availability guarantee.

IoT IPs persist in `/etc/openclash/split-dns/settings.yaml` and are reapplied on
subscription changes. Running the split-DNS installer without `--iot-inventory`
preserves the installed list. Supplying a new inventory replaces the routing list;
old DHCP reservations are retained to avoid reallocating addresses unexpectedly.
An inventory with `"devices": []` clears IoT routing exceptions, not reservations.
IP reservations are operational identification, not protection against IP/MAC spoofing.

Tests: `python3 -m unittest test_iot test_split_dns test_installer test_rules test_mihomo`.
