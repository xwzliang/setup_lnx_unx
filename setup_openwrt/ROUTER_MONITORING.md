# Router monitoring and SQM calibration

Run `./tune_router_monitoring.py` from this directory, optionally with
`--router root@192.168.5.1`. It backs up the modified configuration under
`/root/monitoring-tuning.*` on the router before applying changes.

Install these packages from the matching firmware feed first:

```sh
apk add luci-app-statistics collectd-mod-thermal collectd-mod-conntrack \
  collectd-mod-uptime luci-app-sqm luci-app-irqbalance irqbalance luci-app-nlbwmon
```

The tuning script:

- Keeps statistics RRD files in RAM, avoiding frequent USB writes. Graphs reset
  on reboot. Enables temperature, connection count and uptime collection, and
  selects LAN plus the current WAN device for traffic graphs.
- Saves bandwidth history under `/overlay/nlbwmon` every 24 hours, counting the
  logical LAN rather than every private-address range. Abrupt power loss can
  lose unsaved history. Proxy/TUN traffic accounting must be compared against
  WAN counters; these records are not authoritative provider-quota totals.
- Raises the receive-buffer ceiling to at least 1 MiB and requests a 1 MiB
  nlbwmon buffer. Leaves larger existing system limits intact.
- Enables irqbalance without changing interrupt affinity or packet steering.
- Installs a narrowly guarded workaround for ImmortalWrt kernel **6.12.103**:
  [issue #2496](https://github.com/immortalwrt/immortalwrt/issues/2496) describes
  fullcone probing unregistering conntrack event notifications. The helper
  reloads only `nf_conntrack_netlink` after firewall reloads and at late boot.
  It refuses to run with active fullcone rules and does nothing on other kernel
  versions. It never unloads `nf_conntrack` or resets the connection table.

The helper also runs after the script's `fw4 check`, since the fullcone probe
performed by that command can trigger the bug. If running `fw4 check` manually
on this kernel, run `/usr/libexec/nlbwmon-compat` afterward. After upgrading to a
fixed kernel, remove the `firewall.nlbwmon_compat` include and disable
`/etc/init.d/nlbwmon-compat`; the version guard already makes it inert.

## Calibration on 2026-11-24

The physical router has an i7-7500U, four logical CPUs, 16 GiB RAM and a 1 Gbps
WAN Ethernet link. The user reports a 500 Mbps ISP plan; upload speed and access
technology are not confirmed. CPU/memory pressure was low, and NIC interrupts
were already distributed across CPUs. No additional steering changes were made.

The original bandwidth monitor had zero records. Reloading the telemetry module
restored records, confirming the observed symptom of the upstream issue.
The default buffer request also exceeded the kernel ceiling and was corrected.

The initial speedtest.net lookup used a proxy egress and was rejected as a WAN
calibration source. A direct-bound lookup failed. A browser Speedtest.cn test
identified China Unicom but selected a distant Nanjing server and returned
4.81 Mbps down / 5.76 Mbps up. That is insufficient evidence for a 500 Mbps
WAN shaper setting. **SQM remains disabled, with no claimed throughput gain.**

For SQM, measure download/upload against a nearby ISP server from a wired LAN
client, recording idle and loaded latency. Repeat to establish a stable rate.
Use the WAN layer-3 interface (`pppoe-wan` here), configure CAKE below the measured
bottleneck rates, and compare latency and throughput before/after. Do not copy
the package's example 85/10 Mbps settings or infer upload speed from download.
Keep hardware flow offload disabled. Confirm encapsulation before selecting
overhead values. Do not change provider fallback or proxy rules to tune SQM.

Reference: [OpenWrt SQM details](https://openwrt.org/docs/guide-user/network/traffic-shaping/sqm-details).
