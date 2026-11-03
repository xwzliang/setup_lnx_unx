#!/usr/bin/env python3
"""Upgrade legacy fw3 OpenClash to pinned Mihomo, with LAN tests and rollback."""
import argparse
import hashlib
import gzip
import ipaddress
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import tarfile
import time
from install_openclash_killswitch import Installer, VERIFY

VERSION = '1.19.33'
RELEASES = {
    'x86_64': ('amd64-compatible', '386508bfb1c72c43b6a0eda73708ecdce82546581b0ebcb16366c53757c622b6'),
    'aarch64': ('arm64', 'ba408b317080ee265c46cb923a50018c1b82cbd708551cdd46a1e3e307396187'),
}
SAFE_PATH = '/usr/share/openclash/ui'

RESTORE = r'''#!/bin/sh
set -e
cd "$1"
umask 077
exec >>rollback.log 2>&1
exec 8>decision.lock
flock -x 8
if [ "${2:-}" != force ] && [ ! -f pending ]; then exit 0; fi
/etc/init.d/openclash stop || :
uci revert openclash || :
tar -xzf backup.tar.gz -C /
/usr/sbin/openclash-killswitch apply
/etc/init.d/openclash start
rm -f pending
echo rolled-back >result
'''
WATCH = r'''#!/bin/sh
sleep 900
exec sh "$1/restore.sh" "$1"
'''
UPGRADE = r'''#!/bin/sh
set -e
umask 077
cd "$1"
exec >upgrade.log 2>&1
exec 9>/tmp/lock/setup-mihomo-upgrade.lock
flock -n 9 || { echo busy >result; exit 1; }
trap 'echo failed >result' EXIT
test -z "$(uci changes openclash)"
test "$(uci -q get openclash.config.small_flash_memory)" != 1
test -x /usr/sbin/openclash-killswitch
grep -q enable_meta_core /etc/init.d/openclash
test -f /etc/openclash/core/clash_meta
# Include old cores, config files, custom hooks and independent firewall settings.
tar -czf backup.tar.gz -C / etc/openclash etc/config/openclash etc/config/network etc/config/firewall etc/config/dhcp etc/init.d/openclash etc/openclash-killswitch
# Restoration deliberately extracts only OpenClash-owned files. Network/firewall
# snapshots are retained for reference; this upgrade does not modify those files.
cp backup.tar.gz full-backup.tar.gz
tar -czf backup.tar.gz -C / etc/openclash etc/config/openclash etc/init.d/openclash
gzip -dc core.gz >mihomo
chmod 755 mihomo
rm core.gz
export SAFE_PATHS=/usr/share/openclash/ui
./mihomo -v
raw=$(uci -q get openclash.config.config_path)
./mihomo -t -d /etc/openclash -f "$raw" >source-validation.log 2>&1
./mihomo -t -d /etc/openclash -f "/etc/openclash/${raw##*/}" >runtime-validation.log 2>&1
if [ -s validate-path ]; then
    ./mihomo -t -d /etc/openclash -f "$(cat validate-path)" >extra-validation.log 2>&1
fi
# Start independent recovery before any production mutation. Closing fd 9 keeps
# the watchdog from inheriting the installer's lock.
touch pending
nohup sh "$PWD/watch.sh" "$PWD" >/dev/null 2>&1 </dev/null 9>&- &
mv mihomo /etc/openclash/core/clash_meta.new
chmod 755 /etc/openclash/core/clash_meta.new
mv /etc/openclash/core/clash_meta.new /etc/openclash/core/clash_meta
ruby -e 'p=ARGV[0]; s=File.read(p); line="export SAFE_PATHS=/usr/share/openclash/ui # setup_mihomo_dashboard\n"; unless s.include?(line); abort "Existing SAFE_PATHS customization requires review" if s.include?("SAFE_PATHS"); s=s.sub("\n", "\n"+line); File.write(p,s); end' /etc/init.d/openclash
uci set openclash.config.enable_meta_core=1
uci commit openclash
/etc/init.d/openclash restart 9>&-
trap - EXIT
echo ready >result
'''


def release(arch):
    if arch not in RELEASES:
        raise ValueError('Supported architectures: ' + ', '.join(RELEASES))
    asset, digest = RELEASES[arch]
    return f'https://github.com/MetaCubeX/mihomo/releases/download/v{VERSION}/mihomo-linux-{asset}-v{VERSION}.gz', digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--router', default='192.168.5.1')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--client', required=True, help='SSH alias for a Linux LAN client used for outage tests')
    parser.add_argument('--client-ip', required=True, type=ipaddress.IPv4Address)
    parser.add_argument('--archive', type=Path, help='Use an already downloaded official .gz (checksum still verified)')
    parser.add_argument('--validate-config', help='Additional existing router YAML to check before switching')
    parser.add_argument('--backup-dir', type=Path, default=Path.home()/'.local/state/mihomo-upgrade')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.router) or not 1 <= args.port <= 65535:
        parser.error('Invalid router/SSH port')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', args.client):
        parser.error('Invalid client SSH alias')
    if args.validate_config and not re.fullmatch(r'/[A-Za-z0-9_./-]+', args.validate_config):
        parser.error('Validation config must be an absolute router path without spaces')
    # test_outage currently uses router SSH port 22; avoid silently testing another target.
    if args.port != 22:
        parser.error('Disruptive verification currently requires router SSH port 22')
    with tempfile.TemporaryDirectory(prefix='mihomo-', dir='/tmp') as tmp:
        remote = Installer(args, Path(tmp)/'ssh')
        stage = None
        confirmed = False
        try:
            remote.connect()
            remote.script(VERIFY)
            route = remote.remote(f'ip -4 route get {args.client_ip}')
            if not re.search(r'\bdev br-lan\b', route):
                raise RuntimeError('Outage-test client must be reachable through br-lan')
            url, digest = release(remote.remote('uname -m'))
            archive = args.archive or Path(tmp)/'core.gz'
            if not args.archive:
                subprocess.run(['curl','-fL','--connect-timeout','15','--max-time','180',url,'-o',str(archive)], check=True)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                raise RuntimeError('Official archive checksum mismatch; nothing installed')
            # Estimate compressed backups without filling the router filesystem.
            backup_bytes = int(remote.remote(
                'tar -czf - -C / etc/openclash etc/config/openclash etc/config/network '
                'etc/config/firewall etc/config/dhcp etc/init.d/openclash etc/openclash-killswitch | wc -c',
                timeout=180))
            with gzip.open(archive, 'rb') as compressed:
                core_bytes = sum(len(chunk) for chunk in iter(lambda: compressed.read(1024*1024), b''))
            available = int(remote.remote("df -Pk /root | awk 'NR==2 {print $4}'")) * 1024
            needed = core_bytes + archive.stat().st_size + 2*backup_bytes + 16*1024*1024
            if available < needed:
                raise RuntimeError(f'Insufficient router space: need about {needed//1048576} MiB, have {available//1048576} MiB. Archive/remove old private upgrade backups first.')
            stage = remote.remote('umask 077; mktemp -d /root/mihomo-upgrade.XXXXXX')
            if not re.fullmatch(r'/root/mihomo-upgrade\.[A-Za-z0-9]+', stage):
                raise RuntimeError('Unexpected staging directory')
            with archive.open('rb') as stream:
                subprocess.run(remote.ssh + ['-o','BatchMode=yes',remote.target,f'umask 077; cat >{stage}/core.gz'], stdin=stream, check=True)
            for name, source in [('upgrade.sh',UPGRADE),('restore.sh',RESTORE),('watch.sh',WATCH),('validate-path',args.validate_config or '')]:
                remote.remote(f'umask 077; cat >{stage}/{name}', source)
            print('Private router backup and logs: '+stage, flush=True)
            remote.remote(f'nohup sh {stage}/upgrade.sh {stage} >/dev/null 2>&1 </dev/null &')
            deadline = time.monotonic()+300
            while time.monotonic() < deadline:
                result = remote.remote(f'cat {stage}/result 2>/dev/null || true')
                if result == 'ready': break
                if result: raise RuntimeError(f'Upgrade {result}; inspect {stage}/upgrade.log and *-validation.log')
                time.sleep(3)
            else: raise RuntimeError('Upgrade timed out; automatic rollback remains armed')
            print('Mihomo started; verifying LAN routing and firewall guard.', flush=True)
            remote.script(VERIFY)
            version = remote.remote('/etc/openclash/clash -v')
            if f'Meta v{VERSION}' not in version:
                raise RuntimeError('Running core version does not match expected release')
            remote.remote('test "$(readlink /etc/openclash/clash)" = /etc/openclash/core/clash_meta')
            route = remote.remote(f'ip -4 route get 1.1.1.1 from {args.client_ip} iif br-lan')
            if 'dev utun table 354' not in route: raise RuntimeError('LAN traffic is not using expected TUN route')
            for address in ['http://'+remote.router_ip+'/', 'https://example.com/', 'https://www.baidu.com/']:
                remote.probe(address)
            print('Testing stopped-core + firewall reload, with router-local automatic recovery.', flush=True)
            subprocess.run([sys.executable,str(Path(__file__).with_name('test_outage.py')),
                            '--router',remote.target,'--router-ip',remote.router_ip,'--client',args.client,
                            '--client-ip',str(args.client_ip),'--reload-firewall'], check=True, timeout=180)
            remote.script(VERIFY)
            folder = args.backup_dir.expanduser()/remote.router_ip
            folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            folder.chmod(0o700)
            backup = folder/(Path(stage).name+'.tar.gz')
            fd = os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:
                subprocess.run(remote.ssh+['-o','BatchMode=yes',remote.target,f'cat {stage}/full-backup.tar.gz'],stdout=out,check=True)
            with tarfile.open(backup, 'r:gz') as saved:
                members = {item.name.lstrip('./') for item in saved.getmembers()}
                if not {'etc/openclash/core/clash_meta','etc/config/openclash','etc/init.d/openclash'}.issubset(members):
                    raise RuntimeError('Downloaded backup is missing required restoration files')
            # Serialize confirmation with the independent rollback decision.
            remote.remote(f'cd {stage}; exec 8>decision.lock; flock -x 8; test "$(cat result)" = ready && test -f pending && rm pending && echo confirmed >result')
            confirmed = True
            print('Verified and confirmed Mihomo '+VERSION+'. Local backup: '+str(backup))
            print(f'Rollback: ssh {remote.target} "nohup sh {stage}/restore.sh {stage} force >/dev/null 2>&1 </dev/null &"')
        finally:
            if stage and not confirmed:
                try:
                    remote.remote(f'if test -f {stage}/pending; then nohup sh {stage}/restore.sh {stage} >/dev/null 2>&1 </dev/null & fi')
                    print('Upgrade not confirmed; rollback requested if changes began.',file=sys.stderr)
                except Exception:
                    print('Router watchdog will roll back unconfirmed changes after 15 minutes.',file=sys.stderr)
            subprocess.run(remote.ssh+['-O','exit',remote.target],capture_output=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        sys.exit(1)
