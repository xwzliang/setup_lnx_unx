"""Install first-boot settings into a verified ImmortalWrt x86 ext4 disk image.

Runs on Linux as an ordinary user, with sfdisk and e2fsprogs. Input is a JSON
line followed by the upstream gzip archive. Output is a raw disk image.
"""

import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def customize(source, output, work):
    settings = json.loads(source.readline())
    disk = work / 'disk.img'
    root = work / 'root.ext4'
    with gzip.GzipFile(fileobj=source) as archive, disk.open('wb') as image:
        shutil.copyfileobj(archive, image)
    table = json.loads(run('sfdisk', '--json', disk, capture_output=True).stdout)['partitiontable']
    # The UEFI image also carries partition 128 for legacy BIOS boot.
    partition = next((part for part in table['partitions'] if part['node'] == f'{disk}2'), None)
    if partition is None:
        raise ValueError('Expected the ImmortalWrt ext4 root on partition 2')
    sector_size = table['sectorsize']
    start = partition['start']
    size = partition['size']
    if start <= 0 or size <= 0 or (start + size) * sector_size > disk.stat().st_size:
        raise ValueError('Invalid ImmortalWrt root partition bounds')
    run('dd', f'if={disk}', f'of={root}', f'bs={sector_size}', f'skip={start}', f'count={size}', 'status=none')

    def debugfs(command, writable=False):
        options = ('-w',) if writable else ()
        return run('debugfs', *options, '-R', command, root, capture_output=True).stdout

    def install(path, content, mode):
        payload = work / 'payload'
        payload.write_bytes(content)
        debugfs(f'write {payload} {path}', writable=True)
        for attribute, value in [('uid', 0), ('gid', 0), ('mode', mode)]:
            debugfs(f'set_inode_field {path} {attribute} {value}', writable=True)
        if debugfs(f'cat {path}') != content:
            raise ValueError(f'Could not update {path} in the firmware')

    shadow = debugfs('cat /etc/shadow').decode().splitlines()
    if sum(line.startswith('root:') for line in shadow) != 1:
        raise ValueError('Firmware does not contain the expected root account')
    for index, line in enumerate(shadow):
        if line.startswith('root:'):
            fields = line.split(':')
            fields[1] = settings['password_hash']
            shadow[index] = ':'.join(fields)
    debugfs('rm /etc/shadow', writable=True)
    install('/etc/shadow', ('\n'.join(shadow) + '\n').encode(), '0100600')
    install('/etc/uci-defaults/99-immortalwrt-setup', settings['first_boot'].encode(), '0100755')
    run('e2fsck', '-fn', root, stdout=sys.stderr)
    run('dd', f'if={root}', f'of={disk}', f'bs={sector_size}', f'seek={start}', 'conv=notrunc', 'status=none')
    with disk.open('rb') as image:
        shutil.copyfileobj(image, output)


if __name__ == '__main__':
    # The fixed base keeps paths passed to debugfs free of whitespace.
    with TemporaryDirectory(prefix='immortalwrt-image-', dir='/tmp') as directory:
        customize(sys.stdin.buffer, sys.stdout.buffer, Path(directory))
