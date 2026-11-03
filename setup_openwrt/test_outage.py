#!/usr/bin/env python3
"""Disruptive LAN test, with router-local automatic recovery before stopping Clash."""
import argparse
import ipaddress
import shlex
import subprocess
import time


def ssh(host, command, data=None):
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command],
        input=data, text=True, capture_output=True, timeout=20,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router", default="root@192.168.5.1")
    parser.add_argument("--client", required=True, help="SSH alias for a LAN Linux client")
    parser.add_argument("--router-ip", default="192.168.5.1")
    parser.add_argument("--client-ip", required=True)
    parser.add_argument("--reload-firewall", action="store_true", help="Also reload fw3 while OpenClash is stopped")
    args = parser.parse_args()
    for value in (args.router_ip, args.client_ip):
        ipaddress.IPv4Address(value)

    def probe(url):
        command = (
            "curl -4 --noproxy '*' -sS -o /dev/null -w '%{http_code}' "
            "--connect-timeout 3 --max-time 4 " + shlex.quote(url)
        )
        r = ssh(args.client, command)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    assert ssh(args.router, "test -f /etc/openclash-killswitch/interfaces").returncode == 0, "Guard not installed"
    baseline = probe("https://1.1.1.1/")
    print("Numeric-IP baseline:", baseline, flush=True)
    assert baseline[0] == 0, "Test endpoint must work before outage"

    recovery = """#!/bin/sh
sleep 25
/etc/init.d/openclash start
date > /tmp/ks-test-recovered
"""
    outage = """#!/bin/sh
rm -f /tmp/ks-test-stopped /tmp/ks-test-recovered
nohup sh /tmp/ks-test-recover.sh >/root/ks-test-recovery.log 2>&1 </dev/null &
echo "recovery_pid=$!"
/etc/init.d/openclash stop
for p in $(pidof clash); do kill "$p"; done
RELOAD_FIREWALL
date > /tmp/ks-test-stopped
ip -4 route get 1.1.1.1 from CLIENT_IP iif br-lan
""".replace("CLIENT_IP", args.client_ip).replace(
        "RELOAD_FIREWALL", "/etc/init.d/firewall reload" if args.reload_firewall else ":"
    )
    # Never embed /etc/init.d/openclash in the long-lived process command line:
    # legacy OpenClash stop kills processes matching that literal substring.
    for path, content in (("/tmp/ks-test-recover.sh", recovery), ("/tmp/ks-test-outage.sh", outage)):
        r = ssh(args.router, "umask 077; cat > " + path, content)
        assert r.returncode == 0, r.stderr
    r = ssh(args.router, "nohup sh /tmp/ks-test-outage.sh >/root/ks-test-outage.log 2>&1 </dev/null &")
    assert r.returncode == 0, r.stderr
    deadline = time.monotonic() + 15
    while ssh(args.router, "test -f /tmp/ks-test-stopped").returncode:
        if time.monotonic() > deadline:
            raise RuntimeError("Stop phase timed out; scheduled recovery remains active")
        time.sleep(1)

    offline_ip = probe("https://1.1.1.1/")
    offline_domain = probe("https://example.com/")
    local_http = probe("http://" + args.router_ip + "/")
    route = ssh(args.router, "ip -4 route get 1.1.1.1 from " + args.client_ip + " iif br-lan")
    print("Offline public IP:", offline_ip, flush=True)
    print("Offline domain:", offline_domain, flush=True)
    print("Offline router HTTP:", local_http, flush=True)
    print("Offline router SSH and route:", route.returncode, route.stdout, route.stderr, flush=True)
    # Even if a test fails, allow the already scheduled router-side recovery to run.
    deadline = time.monotonic() + 90
    recovered = False
    while time.monotonic() < deadline:
        if ssh(args.router, "test -f /tmp/ks-test-recovered").returncode == 0:
            if probe("https://1.1.1.1/")[0] == 0:
                recovered = True
                break
        time.sleep(3)
    print("Automatic recovery:", recovered, flush=True)
    failures = []
    if offline_ip[0] == 0: failures.append("numeric-IP request escaped")
    if offline_domain[0] == 0: failures.append("domain request escaped")
    if local_http[0] != 0 or local_http[1] != "200": failures.append("local HTTP unavailable")
    if route.returncode == 255: failures.append("LAN SSH unavailable")
    if route.returncode == 0: failures.append("WAN route remained available")
    if "Permission denied" not in route.stderr and "prohibited" not in route.stderr:
        failures.append("expected prohibit route not observed")
    if not recovered: failures.append("automatic recovery failed")
    if failures:
        raise SystemExit("FAIL: " + "; ".join(failures))
    print("PASS: stopped core blocks WAN; LAN HTTP/SSH survive; recovery is autonomous.")


if __name__ == "__main__":
    main()
