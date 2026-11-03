#!/usr/bin/env python3
"""Install and verify the legacy OpenClash kill switch from a LAN computer."""
import argparse
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time


DISCOVER = r"""
# OpenWrt shell helpers intentionally reference unset optional variables.
set -e
. /lib/functions.sh
network_device() {
    net="$1"
    dev=$(ubus call "network.interface.$net" status 2>/dev/null | jsonfilter -e '@.l3_device') || dev=
    test -n "$dev" || dev=$(uci -q get "network.$net.device") || dev=
    test -n "$dev" || { echo "Cannot resolve network $net; specify --interfaces" >&2; exit 1; }
    printf '%s\n' "$dev"
}
zone() {
    config_get name "$1" name
    case "$name" in
        wan|wan6) ;;
        lan|docker) config_list_foreach "$1" network network_device ;;
        *) echo "Unrecognized zone $name; specify all client interfaces with --interfaces" >&2; exit 1 ;;
    esac
}
config_load firewall
config_foreach zone zone
"""

VERIFY = r"""
set -eu
test -s /etc/openclash-killswitch/interfaces
test -s /etc/openclash-killswitch/backup
/etc/init.d/openclash-killswitch enabled
test "$(uci -q get firewall.@defaults[0].flow_offloading)" = 0
test "$(uci -q get firewall.@defaults[0].flow_offloading_hw)" = 0
test "$(uci -q get openclash.config.china_ip_route)" = 0
test "$(uci -q get firewall.openclash_killswitch.path)" = /etc/openclash-killswitch/firewall-include.sh
test -x /etc/hotplug.d/iface/99-openclash-killswitch
ip -4 route show table 51821 | grep -Eq '^prohibit default[[:space:]]*$'
ip -4 route show table 354 | grep -Eq '^default dev utun scope link[[:space:]]*$'
for dev in $(cat /etc/openclash-killswitch/interfaces); do
    ip -4 rule show | grep -F "iif $dev lookup 51820" >/dev/null
    ip -4 rule show | grep -F "iif $dev lookup 354" >/dev/null
    ip -4 rule show | grep -F "iif $dev lookup 51821" >/dev/null
    iptables -w -t mangle -C FORWARD -i "$dev" -j OC_KS_FORWARD
done
iptables -w -t mangle -C OC_KS_FORWARD -j DROP
if iptables-save | grep -q FLOWOFFLOAD; then
    echo "Flow offloading remains enabled" >&2
    exit 1
fi
for p in /proc/sys/net/ipv6/conf/*/disable_ipv6; do test "$(cat "$p")" = 1; done
raw=$(uci -q get openclash.config.config_path)
active="/etc/openclash/${raw##*/}"
ruby -ryaml -e 'c=YAML.load_file(ARGV[0]); abort "Missing CN DIRECT rule" unless c.fetch("rules").include?("GEOIP,CN,DIRECT"); abort "IPv6 enabled" unless c["ipv6"] == false' "$active"
"""


def interfaces(values):
    result = sorted(set(values))
    if not result or any(not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", x) for x in result):
        raise ValueError("Specify valid client interface names, e.g. --interfaces br-lan wireguard docker0")
    return result


class Installer:
    def __init__(self, args, control):
        self.args = args
        self.payload = Path(__file__).with_name("openclash-killswitch.sh")
        self.target = "root@" + args.router.removeprefix("root@")
        self.ssh = ["ssh", "-p", str(args.port), "-o", "ConnectTimeout=10",
                    "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3",
                    "-o", "ControlMaster=auto", "-o", "ControlPersist=600",
                    "-S", str(control)]
        self.authenticated = False
        self.remote_dir = None

    def remote(self, command, data=None, timeout=30):
        options = ["-o", "BatchMode=yes"] if self.authenticated else []
        r = subprocess.run(self.ssh + options + [self.target, command], input=data,
                           text=True, capture_output=True, timeout=timeout)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip() or f"SSH command failed ({r.returncode})")
        return r.stdout.strip()

    def script(self, source):
        return self.remote("sh -s", source)

    def probe(self, url):
        r = subprocess.run(["curl", "-4", "--noproxy", "*", "-sS", "-o", os.devnull,
                            "-w", "%{http_code}", "--connect-timeout", "5", "--max-time", "15", url],
                           capture_output=True, text=True, timeout=20)
        if r.returncode or not r.stdout.isdigit() or not 200 <= int(r.stdout) < 400:
            raise RuntimeError(f"LAN-client check failed for {url}: {r.stderr.strip() or r.stdout}")

    def connect(self):
        # OpenSSH retains its normal host-key and password/key handling.
        connection = self.remote('printf "%s\\n" "$SSH_CONNECTION"', timeout=120).split()
        self.authenticated = True
        if len(connection) != 4:
            raise RuntimeError("Cannot determine SSH client/router addresses")
        self.client_ip = str(ipaddress.IPv4Address(connection[0]))
        self.router_ip = str(ipaddress.IPv4Address(connection[2]))

    def upload_and_start(self, devices):
        self.remote_dir = self.remote("umask 077; mktemp -d /tmp/ks-deploy.XXXXXX")
        if not re.fullmatch(r"/tmp/ks-deploy\.[a-zA-Z0-9]+", self.remote_dir):
            raise RuntimeError("Unexpected remote staging path")
        q = shlex.quote
        self.remote("cat > " + q(self.remote_dir + "/payload.sh"), self.payload.read_text())
        runner = ("#!/bin/sh\numask 077\n"
                  f"sh {q(self.remote_dir + '/payload.sh')} install "
                  + " ".join(map(q, devices)) + f" > {q(self.remote_dir + '/install.log')} 2>&1\n"
                  + f"printf '%s\\n' \"$?\" > {q(self.remote_dir + '/result')}\n")
        self.remote("cat > " + q(self.remote_dir + "/run.sh"), runner)
        # A detached file-based runner survives SSH loss and OpenClash cleanup.
        self.remote(f"nohup sh {q(self.remote_dir + '/run.sh')} >/dev/null 2>&1 </dev/null &")
        print("Installation running on router; brief internet interruption expected.", flush=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                result = self.remote(f"if test -f {q(self.remote_dir + '/result')}; then cat {q(self.remote_dir + '/result')}; else echo running; fi")
            except (RuntimeError, subprocess.TimeoutExpired):
                time.sleep(3)
                continue
            if result != "running":
                if result != "0":
                    log = self.remote("tail -30 " + q(self.remote_dir + "/install.log"))
                    raise RuntimeError("Router installer failed:\n" + log)
                return
            time.sleep(3)
        raise RuntimeError("Installation exceeded 10 minutes; automatic confirmation was not sent")

    def verify(self, devices):
        installed = interfaces(self.remote("cat /etc/openclash-killswitch/interfaces").split())
        if installed != devices:
            raise RuntimeError("Installed interface list does not match requested interfaces")
        self.script(VERIFY)
        route = self.remote("ip -4 route get 1.1.1.1 from " + self.client_ip + " iif " + shlex.quote(self.ingress))
        if "dev utun table 354" not in route:
            raise RuntimeError("Client traffic is not routed through OpenClash's TUN")
        self.probe("http://" + self.router_ip + "/")
        self.probe("https://example.com/")
        self.probe("https://www.baidu.com/")

    def backup(self):
        path = self.remote("cat /etc/openclash-killswitch/backup")
        if not re.fullmatch(r"/root/openclash-killswitch-backup-\d{8}-\d{6}", path):
            raise RuntimeError("Unexpected backup path")
        folder = self.args.backup_dir.expanduser() / self.router_ip
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
        archive = folder / (Path(path).name + ".tar.gz")
        fd, temporary = tempfile.mkstemp(prefix=".backup-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as out:
                r = subprocess.run(self.ssh + ["-o", "BatchMode=yes", self.target,
                    "tar -czf - -C /root " + shlex.quote(Path(path).name)], stdout=out,
                    stderr=subprocess.PIPE, timeout=120)
            if r.returncode:
                raise RuntimeError("Backup download failed: " + r.stderr.decode(errors="replace"))
            # Validate the archive before confirming the router installation.
            with tarfile.open(temporary, "r:gz") as tar:
                expected = Path(path).name + "/restore.tar.gz"
                if expected not in {m.name.removeprefix("./") for m in tar.getmembers()}:
                    raise RuntimeError("Downloaded backup lacks restoration archive")
            os.replace(temporary, archive)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return archive

    def wait_verified(self, devices):
        deadline = time.monotonic() + 120
        while True:
            try:
                self.verify(devices)
                return
            except (RuntimeError, subprocess.SubprocessError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(3)

    def run(self):
        if not self.payload.is_file():
            raise RuntimeError(f"Missing sibling installer: {self.payload}")
        self.connect()
        existing = self.remote("if test -d /etc/openclash-killswitch; then echo yes; else echo no; fi") == "yes"
        if self.args.interfaces:
            devices = interfaces(self.args.interfaces)
        elif existing:
            devices = interfaces(self.remote("cat /etc/openclash-killswitch/interfaces").split())
        else:
            devices = interfaces(self.script(DISCOVER).split())
        route = self.remote("ip -4 route get " + self.client_ip)
        match = re.search(r"\bdev (\S+)", route)
        if not match or match[1] not in devices:
            raise RuntimeError("Run from a protected IPv4 LAN interface, not WAN/VPN outside the selected interfaces")
        self.ingress = match[1]
        print(f"Router: {self.target}; protected interfaces: {', '.join(devices)}", flush=True)
        if existing:
            digest = self.remote("sha256sum /usr/sbin/openclash-killswitch").split()[0]
            if digest != hashlib.sha256(self.payload.read_bytes()).hexdigest():
                raise RuntimeError("Installed script differs; refusing an implicit upgrade. Review/rollback before reinstalling")
            print("Matching installation already exists; verifying without a restart.", flush=True)
        else:
            self.probe("https://example.com/")
            self.probe("https://www.baidu.com/")
            self.upload_and_start(devices)
        self.wait_verified(devices)
        archive = self.backup()
        self.remote("/usr/sbin/openclash-killswitch confirm")
        print(f"Done: verified and confirmed. Private local backup: {archive}")
        print(f"Rollback: ssh -p {self.args.port} {self.target} '/usr/sbin/openclash-killswitch rollback'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--router", default="192.168.5.1", help="Router IPv4 address or SSH host alias (default: 192.168.5.1)")
    parser.add_argument("--port", type=int, default=22, help="SSH port")
    parser.add_argument("--interfaces", nargs="+", help="All trusted client interfaces; otherwise detect LAN/Docker zones")
    parser.add_argument("--backup-dir", type=Path, default=Path.home()/".local/state/openclash-killswitch")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:root@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*", args.router) or not 1 <= args.port <= 65535:
        parser.error("Use an IPv4 address/SSH alias and a valid port")
    for tool in ("ssh", "curl"):
        if not shutil.which(tool): parser.error(f"Missing required command: {tool}")
    with tempfile.TemporaryDirectory(prefix="ks-", dir="/tmp") as directory:
        installer = Installer(args, Path(directory)/"ssh")
        try:
            installer.run()
        except (RuntimeError, ValueError, OSError, tarfile.TarError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
            print(f"Installation not confirmed: {exc}", file=sys.stderr)
            print("If the router installer reached its changes phase, its 30-minute rollback remains armed.", file=sys.stderr)
            if installer.remote_dir: print("Router installation log: " + installer.remote_dir + "/install.log", file=sys.stderr)
            return 1
        finally:
            if installer.authenticated:
                try:
                    subprocess.run(installer.ssh + ["-O", "exit", installer.target],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                except subprocess.SubprocessError:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
