#!/usr/bin/env python3
"""Install persistent split DNS on an existing Mihomo/OpenClash + kill switch router."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from install_openclash_killswitch import Installer, VERIFY
from install_openclash_subscription import PREAMBLE

HERE = Path(__file__).resolve().parent

RESTORE = r'''#!/bin/sh
set -eu
cd "$1"
exec >>restore.log 2>&1
exec 9>/tmp/lock/setup-openclash-subscription.lock
flock -x 9
exec 7>decision.lock
flock -x 7
if [ "${2:-}" != force ] && [ ! -f pending ]; then exit 0; fi
while IFS= read -r file; do
    if [ -f "backup$file" ]; then
        cp -p "backup$file" "$file.restore"
        mv "$file.restore" "$file"
    else
        rm -f "$file"
    fi
done <manifest
cp backup/openclash /etc/config/openclash
rm -f pending
/etc/init.d/openclash restart 9>&- 7>&-
/usr/sbin/openclash-killswitch apply
echo rolled-back >result
'''
WATCH = '#!/bin/sh\nsleep 600\nexec sh "$1/restore.sh" "$1"\n'
HOOK_TEXT = '''#!/bin/sh
# setup_openclash_split_dns: run after all existing OpenClash overrides.
set -e
if [ -f /etc/openclash/split-dns/previous-overwrite.sh ]; then
    sh /etc/openclash/split-dns/previous-overwrite.sh "$@" || echo "Previous overwrite failed; enforcing split DNS anyway" >&2
fi
exec ruby /etc/openclash/split-dns/split_dns.rb "$1" /etc/openclash/split-dns/settings.yaml
'''
VALIDATE = r'''
phase split-dns-preflight
export SAFE_PATHS=/usr/share/openclash/ui
test -x /usr/sbin/openclash-killswitch
test -s /etc/openclash/GeoSite.dat
raw=$(uci -q get openclash.config.config_path)
runtime="/etc/openclash/${raw##*/}"
cp "$runtime" candidate.yaml
ruby split_dns.rb candidate.yaml settings.yaml
validate_core "$PWD/candidate.yaml" split-dns
'''
APPLY = r'''
phase backup
cp /etc/config/openclash backup/openclash
mkdir -p /etc/openclash/split-dns
for file in /etc/openclash/custom/openclash_custom_overwrite.sh /etc/openclash/split-dns/previous-overwrite.sh /etc/openclash/split-dns/split_dns.rb /etc/openclash/split-dns/settings.yaml "$runtime"; do
    printf '%s\n' "$file" >>manifest
    mkdir -p "backup${file%/*}"
    if [ -f "$file" ]; then cp -p "$file" "backup$file"; fi
done
# Full configuration snapshot, no core binaries or credentials printed.
tar -czf config-backup.tar.gz -C / etc/config/openclash etc/config/dhcp etc/config/network etc/config/firewall etc/openclash/custom "${raw#/}" "${runtime#/}" etc/openclash-killswitch
touch pending
nohup sh "$PWD/watch.sh" "$PWD" >watch.log 2>&1 8>&- 9>&- </dev/null &
mutated=1
restart_needed=1
phase install-split-dns
if ! grep -q '^# setup_openclash_split_dns:' /etc/openclash/custom/openclash_custom_overwrite.sh; then
    cp -p /etc/openclash/custom/openclash_custom_overwrite.sh /etc/openclash/split-dns/previous-overwrite.sh
fi
cp split_dns.rb settings.yaml /etc/openclash/split-dns/
cp hook.sh /etc/openclash/custom/openclash_custom_overwrite.sh
chmod 755 /etc/openclash/custom/openclash_custom_overwrite.sh
uci set openclash.config.enable_custom_domain_dns_server=0
uci set openclash.config.china_ip_route=0
uci set openclash.config.proxy_mode=rule
uci commit openclash
restart_core
phase verify-split-dns
pidof clash >/dev/null
validate_core "$runtime" live
# Transform is deterministic: generated config must already contain the policy.
cp "$runtime" verify.yaml
ruby split_dns.rb verify.yaml settings.yaml
ruby -ryaml -e 'abort "Runtime does not match split DNS policy" unless YAML.load_file(ARGV[0]) == YAML.load_file("verify.yaml")' "$runtime"
/usr/sbin/openclash-killswitch apply
trap - EXIT HUP INT TERM
log 'Ready; awaiting LAN verification (automatic rollback in ten minutes unless confirmed)'
echo ready >result
'''


def worker(check_only=False):
    return PREAMBLE.replace("echo rolled-back >result", "rm -f pending\n        echo rolled-back >result") + VALIDATE + ("trap - EXIT HUP INT TERM\necho validated >result\n" if check_only else APPLY)


def save_backup(remote, stage):
    directory = Path.home()/'.local/state/openclash-split-dns'/remote.router_ip
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory/(stage.rsplit('/', 1)[1]+'.tar.gz')
    source = stage+'/config-backup.tar.gz'
    expected = remote.remote('sha256sum '+source).split()[0]
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            subprocess.run(remote.ssh+[remote.target, 'cat '+source], stdout=output,
                           stderr=subprocess.PIPE, check=True, timeout=60)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Backup checksum mismatch')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--router', default='192.168.5.1')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--proxy-group', default='新加坡', help='Proxy-only group for unmatched traffic and default DNS')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.router) or not 1 <= args.port <= 65535:
        parser.error('Invalid router or SSH port')
    if not args.proxy_group or any(c in args.proxy_group for c in '\r\n,#&'):
        parser.error('Invalid proxy group name')
    # YAML double quoted scalar, JSON escaping is valid YAML here.
    import json
    settings = 'proxy_group: ' + json.dumps(args.proxy_group, ensure_ascii=False) + '\n'
    with tempfile.TemporaryDirectory(prefix='oc-dns-', dir='/tmp') as temp:
        remote = Installer(args, Path(temp)/'ssh')
        stage = None
        try:
            remote.connect()
            route = remote.remote('ip -4 route get '+remote.client_ip)
            if 'dev br-lan' not in route.splitlines()[0]:
                raise RuntimeError('Run this installer from a router LAN client (br-lan)')
            stage = remote.remote('umask 077; mktemp -d /root/openclash-split-dns.XXXXXX')
            if not re.fullmatch(r'/root/openclash-split-dns\.[A-Za-z0-9]+', stage):
                raise RuntimeError('Unexpected staging directory')
            for name, content in [('split_dns.rb', (HERE/'split_dns.rb').read_text()), ('settings.yaml', settings),
                                  ('hook.sh', HOOK_TEXT), ('restore.sh', RESTORE), ('watch.sh', WATCH),
                                  ('run.sh', worker(args.check_only))]:
                remote.remote(f'umask 077; cat >{stage}/{name}', content)
            print('Private router configuration backup and logs: '+stage, flush=True)
            remote.remote(f'nohup sh {stage}/run.sh {stage} >/dev/null 2>&1 </dev/null &')
            deadline = time.monotonic()+360
            while time.monotonic()<deadline:
                result = remote.remote(f'cat {stage}/result 2>/dev/null || true')
                if result:
                    break
                time.sleep(3)
            else:
                raise RuntimeError('Worker timed out; router watchdog remains active')
            if result == 'validated':
                print('Policy and core validation passed; no settings changed.')
                return
            if result != 'ready':
                raise RuntimeError(f'Split DNS {result}; inspect {stage}/worker.log')
            local_backup = save_backup(remote, stage)
            print('Private local configuration backup: '+str(local_backup), flush=True)
            remote.script(VERIFY)
            # Local device is the test client; never use Claude/Anthropic test URLs.
            for url in ['https://www.baidu.com/', 'https://example.com/', 'http://'+remote.router_ip+'/']:
                r = subprocess.run(['curl','-4','--noproxy','*','--interface',remote.client_ip,
                                    '--connect-timeout','8','--max-time','20','-fsS','-o','/dev/null',url],
                                   text=True,capture_output=True,timeout=25)
                if r.returncode:
                    raise RuntimeError('LAN connectivity verification failed for '+url)
            remote.remote(f'cd {stage}; exec 7>decision.lock; flock -x 7; test -f pending && test "$(cat result)" = ready && rm pending && echo confirmed >result')
            print('Split DNS installed; mainland, proxy, LAN and kill-switch checks passed.')
            print(f'Rollback: ssh -p {args.port} {remote.target} '+shlex.quote(f'nohup sh {stage}/restore.sh {stage} force >/dev/null 2>&1 </dev/null &'))
        except Exception:
            if stage and not args.check_only:
                try:
                    remote.remote(f'if test -f {stage}/pending; then nohup sh {stage}/restore.sh {stage} >/dev/null 2>&1 </dev/null & fi')
                except Exception:
                    print('Router watchdog will restore unconfirmed settings.', file=sys.stderr)
            raise
        finally:
            subprocess.run(remote.ssh+['-O','exit',remote.target],capture_output=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError,RuntimeError,OSError,subprocess.SubprocessError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        sys.exit(1)
