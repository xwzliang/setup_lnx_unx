# ImmortalWrt migration and recovery plan

Status: planning only; no firmware installation, reboot, disk writes or migration
has been performed. Proposed scripts below do not exist yet. Reconfirm versions
and hardware state before execution. Overlay expansion remains deferred.

## Objective and known baseline

Migrate ImmortalWrt 21.02.7 to a tested stable release with compatible OpenClash
and Mihomo, preserving local administration, DHCP reservations, WireGuard, Docker
subconverter, subscription preference/regional fallback, split DNS, explicit DIRECT
rules, IoT exceptions, IPv6-disabled policy and fail-closed forwarding.

As checked on 2026-11-05, official downloads list 25.12.2 for x86/64. Treat this as
an initial candidate, not an automatically approved target or a floating `latest`.
The current disk is a 128 GB BEIKONG SSD (/dev/sda, about 119 GiB), DOS partition
table: sda1 16 MiB boot, sda2 800 MiB squashfs plus F2FS overlay, sda3 30 GiB ext4
mounted at /opt/docker. Remaining space is unused. Verify boot firmware mode,
NIC MAC-to-role mapping and disk serial/size before selecting an image. Device
names such as /dev/sda can change when USB storage is attached.

## Recovery boundary

There is no honest guarantee of remote rollback after a bootloader failure,
unbootable kernel, wrong NIC mapping, power failure, or inaccessible LAN. An SSH
watchdog cannot repair a router that never boots. Checksums prove an archive was
copied intact, not that it can boot. A LuCI/sysupgrade configuration backup does
not preserve installed packages, the old core, bootloader, Docker data or all
custom files. Existing configuration archives are not complete system recovery.

Preferred approach: install the candidate on a spare SSD (or suitable external
SSD if booting it is supported), keeping the original disk physically disconnected
and unchanged. Test booting the spare before making it the production default.
Rollback is then power off, reconnect/select the original disk and boot it.
Do not let the candidate mount or modify the original Docker partition. Clone
needed Docker data to the candidate. Record that returning to the original disk
also returns data/configuration to the cutover point.

Also keep an offline, consistent image of the original disk on another machine
or external storage. Boot a rescue USB and image the unmounted disk, including
partition table, boot sectors and all three partitions. Do not call a live `dd`
of writable F2FS/Docker data a consistent backup. Plan up to 128 GB for the raw
image plus working space; compression is not guaranteed. Record disk geometry,
serial, image byte count and SHA-256; test reading/decompressing the full image.
Prove recovery by restoring to a spare disk of sufficient exact byte capacity
and booting it, ideally on this hardware. Keep keys and subscription credentials
private (0700 directory, 0600 artifacts, encrypted off-device storage).

If no spare boot device is available, in-place migration is the second choice:
require rescue boot to be tested, full image verified and preferably restore-tested,
and a local operator available. Never blindly write a combined image to the
production /dev/sda: it contains a partition table and may destroy the Docker
layout. Inspect the exact installed/target sysupgrade implementation before
assuming partition preservation. Do not flash or force past compatibility checks.

## Preparation gates

1. Confirm local console/display+keyboard or serial access, rescue USB boot,
   a wired management laptop with static-IP fallback, spare storage and a
   maintenance window. Download recovery tools before interrupting Internet.
2. Collect read-only inventory: release/kernel, BIOS/UEFI, disk identifiers and
   partition boundaries, filesystems, NIC MACs/roles, WAN/PPPoE, WireGuard,
   package versions, firewall/routing state, OpenClash/core versions, selected
   subscription, DNS settings and all persistent hooks. Do not print secrets.
3. Export a private configuration snapshot plus full custom scripts, core binaries,
   OpenClash source/runtime configs, rule/geodata files, .env, package inventory,
   container image digest, mounts and volumes. Archive Docker data consistently
   while stopped or from the offline image. Keep a second copy off the router.
4. Pin firmware, OpenClash, Mihomo and container artifacts with exact versions,
   URLs and hashes. Verify official signatures when provided using independently
   trusted keys; a checksum downloaded beside an image alone does not establish
   authenticity. Package format/dependencies must match target apk/nftables.
5. Create a candidate config from supported settings. Do not restore the entire
   21.02 /etc tree, old binaries, old firewall includes or old opkg feeds wholesale.
   Preserve named intent and migrate schema/package differences explicitly.

## Code that must be ready before migration

- Add a native nftables backend for openclash-killswitch.sh and its verifier.
  Preserve early-boot/restart protection, protected ingress interfaces, TUN policy
  routing/prohibit fallback, disabled offloading and IPv6 handling. Do not rely
  on legacy iptables compatibility behavior. Check hook priorities against the
  target OpenClash, firewall4 and Docker rules.
- Port router-service-guard.sh to nftables with the same trusted interfaces and
  router-addressed service restrictions before DNAT. Preserve WireGuard ingress.
- Make package/dependency installers detect opkg versus apk, fail on unsupported
  combinations, and avoid broad package upgrades.
- Revalidate OpenClash overwrite hook ordering and failure handling. Preserve
  subscription conversion, region preference, backup-node refresh, split DNS,
  hostname sniffing, and the 24 current IoT exceptions/reservations.
- Maintain separate fw3 and fw4 tests so the existing router remains supportable.
  Existing current-version scripts are not yet certified for 25.12.

## Candidate installation and cutover

First test the candidate in an isolated VM/network: no production DHCP server,
no duplicate production LAN IP, and no use of live WireGuard identity on the same
network. Install current compatible OpenClash and required dependencies, then
restore selected settings and custom policies. VM tests validate logic, not NIC
hardware compatibility; require a physical candidate boot too.

Bootstrap protection must be present before connecting production clients to WAN.
Do not allow a temporary default LAN-to-WAN forwarding path while installing
OpenClash. Prestage packages or use controlled router-originated setup access.
Install base firewall/service guards, confirm default deny, then activate routing,
DNS, proxy core and Docker. Keep the original disk disconnected.

At cutover, disconnect/stop the old router before candidate DHCP/LAN identity is
activated. First confirm local SSH/LuCI; then WAN, WireGuard and the application
checks below. Establish a local confirmation deadline. An on-router watchdog may
restore candidate configuration for failures where the OS remains operational;
its confirmation token must follow the new boot and independent LAN checks.
It must never claim it can revert firmware on this non-A/B installation.

## Acceptance matrix

- Correct boot disk, healthy filesystems, preserved candidate Docker data.
- LAN SSH/LuCI and DHCP reservations; DNS available to normal clients.
- Mainland known-domain DIRECT, unknown-domain proxy, subscription foreign-DIRECT
  rules, and IoT-only known-mainland-IP exception all behave as intended.
- Router DNS goes through configured proxy except explicit direct/bootstrap cases;
  no unintended WAN DNS escape. Use scoped probes/counters, not broad DNS capture.
- IPv6 remains disabled; offloading remains disabled unless independently proven safe.
- Preferred provider remains preferred while healthy; isolated local-proxy test
  verifies failure of one node, all regional nodes, and recovery/failback.
- Kill switch blocks LAN/WireGuard/Docker Internet egress with core stopped and
  during firewall reload/restart; LAN administration survives. Router-local
  recovery timer armed before fault injection. No Claude/Anthropic test requests.
- Real external client confirms proxy/admin/converter ports are closed on WAN;
  test WireGuard from an external network and trusted proxy use over WireGuard.
- Subconverter local fetch/conversion, core config validation, and both provider
  configs work without unnecessary subscription downloads.
- Repeat critical checks after reboot, firewall reload, OpenClash restart and
  Docker restart. Compare idle latency and controlled under-load measurements;
  do not promise a throughput increase. Observe normal household use for 24–48h.

Fail acceptance: return to the untouched original disk. Do not spend the outage
window debugging indefinitely. Keep original disk and backups until a separately
agreed retention period expires; never automatically delete them after success.

## Proposed reusable automation (not implemented)

A single local Python CLI `router_upgrade.py`, with separate explicit phases:

| Phase | Action | Safety boundary |
|---|---|---|
| `inventory` | Read-only SSH discovery, sanitized report + private inventory | No installs or reboots |
| `prepare` | Download pinned artifacts, validate hashes/signatures, render candidate | No production writes |
| `backup-config` | Private exports and off-device checksum verification | Not labeled full recovery |
| `backup-disk` | Rescue-environment offline image workflow | Requires unmounted source and local recovery |
| `stage` | Install/configure only explicitly identified spare disk/candidate | Refuse production disk and ambiguous identity |
| `verify` | LAN/core/firewall/routing checks and structured result | Disruptive tests separately opted in |
| `cutover` | Guided local boot change and confirmation workflow | Explicit target + maintenance authorization |
| `rollback` | Guided original-disk boot or rescue image restore | Restore target identity checked independently |

Example future invocation shape (do not run; CLI not created):

    router_upgrade.py inventory --router 192.168.5.1
    router_upgrade.py prepare --plan migration.json
    router_upgrade.py verify --plan migration.json

`migration.json` should contain only non-secret intent: source/target releases,
artifact hashes, boot mode, disk identity, NIC mappings, service inventory,
expected checks and recovery method. Private payloads live outside Git. Plans
must include a schema version and reject stale source fingerprints at execution.
Use per-run IDs, private logs, atomic progress records, a lock shared with existing
installers and resumable steps. Re-discover disk/NIC identities before writes;
never derive permission to format from a remembered /dev/sdX name. Do not embed
an unchecked shell command from inventory or subscription data. Report completed,
failed and untested checks separately. No automatic `latest`, `--force`, reboot,
formatting, firmware writes or backup deletion as a side effect of planning.

## References

- Official target artifacts: https://downloads.immortalwrt.org/releases/25.12.2/targets/x86/64/
- OpenClash installation/dependencies: https://github.com/vernesong/OpenClash
- OpenWrt x86 partition and backup guidance: https://openwrt.org/docs/guide-user/installation/openwrt_x86
