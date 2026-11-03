#!/usr/bin/env python3
"""Sync the priority custom-rules field in OpenClash from a local YAML file."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from install_openclash_killswitch import Installer
from install_openclash_subscription import PREAMBLE

HERE = Path(__file__).resolve().parent
RULES_PATH = '/etc/openclash/custom/openclash_custom_rules.list'

VALIDATE = r'''
phase validating-rules
export SAFE_PATHS=/usr/share/openclash/ui
raw=$(uci -q get openclash.config.config_path)
runtime="/etc/openclash/${raw##*/}"
test -s "$runtime" || { log 'ERROR: OpenClash must have an existing generated runtime config'; exit 1; }
ruby -ryaml -e '
  rules=YAML.load_file("rules.yaml") || []
  abort "Custom rules must be a YAML list of nonempty strings" unless rules.is_a?(Array) && rules.all?{|r| r.is_a?(String) && !r.strip.empty?}
  config=YAML.load_file(ARGV[0])
  old=File.exist?(ARGV[1]) ? (YAML.load_file(ARGV[1]) || []) : []
  abort "Existing custom rules are not a list" unless old.is_a?(Array)
  config["rules"]=(rules + config.fetch("rules",[]).reject{|r| old.include?(r)}).uniq
  File.write("candidate.yaml",config.to_yaml)
  puts "Custom rules: #{rules.size} entries; #{rules.uniq.size} unique"
' "$runtime" /etc/openclash/custom/openclash_custom_rules.list
validate_core "$PWD/candidate.yaml" rules
'''
APPLY = r'''
# If both stored and live rules already match, avoid interrupting connections.
if cmp -s rules.yaml /etc/openclash/custom/openclash_custom_rules.list &&
   [ "$(uci -q get openclash.config.enable_custom_clash_rules)" = 1 ] &&
   ruby -ryaml -e 'a=(YAML.load_file("rules.yaml") || []).uniq; b=YAML.load_file(ARGV[0]).fetch("rules",[]); indices=a.map{|r| b.index(r)}; exit(indices.all? && indices==indices.sort ? 0 : 1)' "$runtime"; then
    log 'Rules already stored and active; no restart needed'
    trap - EXIT HUP INT TERM
    echo unchanged >result
    exit 0
fi
phase backup
cp /etc/config/openclash backup/openclash
file=/etc/openclash/custom/openclash_custom_rules.list
printf '%s\n' "$file" >manifest
mkdir -p "backup${file%/*}"
if [ -f "$file" ]; then cp -p "$file" "backup$file"; fi
log "Backup: $PWD/backup"
mutated=1
restart_needed=1
phase installing-rules
mkdir -p /etc/openclash/custom
cp rules.yaml "$file.new"
chmod 644 "$file.new"
mv "$file.new" "$file"
uci set openclash.config.enable_custom_clash_rules=1
uci commit openclash
phase restarting
restart_core
phase verifying-live-rules
pidof clash >/dev/null
validate_core "$runtime" applied
ruby -ryaml -e '
  wanted=(YAML.load_file("rules.yaml") || []).uniq
  actual=YAML.load_file(ARGV[0]).fetch("rules",[])
  indices=wanted.map{|r| actual.index(r)}
  abort "Requested rules missing or reordered in generated runtime config" unless indices.all? && indices==indices.sort
' "$runtime"
if [ -x /usr/sbin/openclash-killswitch ]; then
    /usr/sbin/openclash-killswitch apply
    ip -4 route show table 354 | grep -q 'default dev utun'
fi
trap - EXIT HUP INT TERM
log 'Custom rules installed and verified'
echo installed >result
'''


def worker(check_only=False):
    tail = "trap - EXIT HUP INT TERM\nlog 'Validation passed; nothing changed'\necho validated >result\n" if check_only else APPLY
    return PREAMBLE + VALIDATE + tail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--router', default='192.168.5.1', help='Router address or SSH alias')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--file', type=Path, default=HERE/'openclash_custom_rules.yaml')
    parser.add_argument('--check-only', action='store_true', help='Validate without saving or restarting')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.router) or not 1 <= args.port <= 65535:
        parser.error('Invalid router address/alias or SSH port')
    rules = args.file.read_text().replace('\r\n','\n').replace('\r','\n')
    with tempfile.TemporaryDirectory(prefix='oc-rules-', dir='/tmp') as temp:
        remote = Installer(args, Path(temp)/'ssh')
        try:
            remote.connect()
            stage = remote.remote('umask 077; mktemp -d /root/openclash-rules.XXXXXX')
            if not re.fullmatch(r'/root/openclash-rules\.[A-Za-z0-9]+',stage):
                raise RuntimeError('Unexpected staging directory')
            remote.remote(f'umask 077; cat >{stage}/rules.yaml',rules)
            remote.remote(f'umask 077; cat >{stage}/run.sh',worker(args.check_only))
            remote.remote(f'nohup sh {stage}/run.sh {stage} >/dev/null 2>&1 </dev/null &')
            print('Private router backups and logs: '+stage,flush=True)
            deadline=time.monotonic()+360
            while time.monotonic()<deadline:
                result=remote.remote(f'cat {stage}/result 2>/dev/null || true')
                if result:
                    if result not in ('validated','installed','unchanged'):
                        raise RuntimeError(f'Rules update {result}; inspect {stage}/worker.log')
                    print('Rules '+result+'.')
                    return
                time.sleep(3)
            raise RuntimeError('Timed out; detached worker continues. Inspect '+stage+'/result')
        finally:
            subprocess.run(remote.ssh+['-O','exit',remote.target],capture_output=True)


if __name__=='__main__':
    try:
        main()
    except (ValueError,RuntimeError,OSError,subprocess.SubprocessError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        sys.exit(1)
