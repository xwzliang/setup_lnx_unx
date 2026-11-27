#!/usr/bin/env python3
"""Download, configure, and install a clean ImmortalWrt x86-64 system."""

import argparse
from functools import partial
import getpass
import hashlib
from ipaddress import IPv4Interface, IPv4Network
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from immortalwrt_router_profile import add_file, load_profile, render_profile, write_profile

RELEASE = '25.12.2'
DOWNLOADS = 'https://downloads.immortalwrt.org/releases'
ARCHIVE = Path('/Volumes/omv/OS/openwrt/immortalwrt')
CHECKSUMS = {
    'uefi': '63321cd582c61ce0d7cc62823b1594e3401037550e7b3a3c03c4b18c8f368545',
    'bios': 'ef32f63bfca995eb710c0339312aa702a1eb9f6ece312f5e311ee9436a0243d8',
}
IMAGE_WORKER = Path(__file__).with_name('immortalwrt_image.py')
PROXMOX_WORKER = Path(__file__).with_name('provision_immortalwrt.sh')
OPENCLASH_WORKER = Path(__file__).with_name('build_immortalwrt_openclash.sh')
BUILDER_DOCKERFILE = Path(__file__).with_name('immortalwrt_openclash.Dockerfile')
SUBCONVERTER_INIT = Path(__file__).with_name('immortalwrt_subconverter.init')
IMAGEBUILDER = f'immortalwrt-imagebuilder-{RELEASE}-x86-64.Linux-x86_64.tar.zst'
OPENCLASH_APK = 'luci-app-openclash-0.48.002.apk'
GITHUB_RELEASE = 'https://github.com/vernesong/OpenClash/releases/download/v0.48.002/'
CHUNK_SIZE = 1024 ** 2


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def ssh_command(host, *args):
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '--', host, shlex.join(args)]


def checksum(source, length=None):
    digest = hashlib.sha256()
    while length is None or length > 0:
        data = source.read(CHUNK_SIZE if length is None else min(CHUNK_SIZE, length))
        if not data:
            if length:
                raise ValueError('Unexpected end of image during verification')
            break
        digest.update(data)
        if length is not None:
            length -= len(data)
    return digest.hexdigest()


def download_image(release, firmware, directory):
    suffix = '-efi' if firmware == 'uefi' else ''
    name = f'immortalwrt-{release}-x86-64-generic-ext4-combined{suffix}.img.gz'
    url = f'{DOWNLOADS}/{release}/targets/x86/64/'
    if release == RELEASE:
        expected = CHECKSUMS[firmware]
    else:
        with urlopen(url + 'sha256sums', timeout=30) as manifest:
            matches = [line.split() for line in manifest.read().decode().splitlines()
                       if line.split() and line.split()[-1].lstrip('*') == name]
        if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{64}', matches[0][0]):
            raise ValueError(f'No unique published SHA-256 for {name}')
        expected = matches[0][0]

    return verified_download(url + name, directory, name, expected)


def verified_download(url, directory, name, expected):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if not path.exists():
        with TemporaryDirectory(prefix='.immortalwrt-', dir=directory) as stage:
            pending = Path(stage) / name
            with urlopen(url, timeout=60) as source, pending.open('wb') as output:
                shutil.copyfileobj(source, output)
            with pending.open('rb') as source:
                if checksum(source) != expected:
                    raise ValueError(f'Download failed the SHA-256 check for {name}')
            pending.replace(path)
    with path.open('rb') as source:
        if checksum(source) != expected:
            raise ValueError(f'Existing image failed the SHA-256 check: {path}')
    return path


def first_boot(args, public_key):
    commands = [
        f'uci set {shlex.quote("system.@system[0].hostname=" + args.hostname)}',
        f'uci set {shlex.quote("system.@system[0].zonename=" + args.zone)}',
        f'uci set {shlex.quote("system.@system[0].timezone=" + args.timezone)}',
        f'uci set {shlex.quote("network.lan.ipaddr=" + str(args.lan))}',
        '(uci -q delete network.lan.netmask || true)',
        'uci commit system',
        'uci commit network',
    ]
    if args.router_profile:
        commands.extend([
            'ln -sf /etc/openclash/core/clash_meta /etc/openclash/clash',
            '/etc/init.d/openclash enable',
        ])
    if args.no_dhcp:
        commands.extend([
            'uci set dhcp.lan.ignore=1',
            'uci set dhcp.lan.dhcpv6=disabled',
            'uci set dhcp.lan.ra=disabled',
            'uci commit dhcp',
        ])
    if public_key:
        commands.extend([
            'umask 077',
            'mkdir -p /etc/dropbear',
            f'printf "%s\\n" {shlex.quote(public_key)} > /etc/dropbear/authorized_keys',
        ])
    # The boot service retries uci-defaults scripts that exit unsuccessfully.
    return '#!/bin/sh\n' + ' &&\n'.join(commands) + '\n'


def image_settings(args):
    if args.password_file:
        password = args.password_file.read_text().rstrip('\r\n')
    else:
        password = getpass.getpass('New ImmortalWrt root password: ')
        if password != getpass.getpass('Confirm root password: '):
            raise ValueError('The passwords did not match')
    if not password or any(char in password for char in '\r\n\0'):
        raise ValueError('The root password must be a nonempty single line')
    password_hash = run('openssl', 'passwd', '-6', '-stdin', input=password + '\n',
                        capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'\$6\$[./A-Za-z0-9]+\$[./A-Za-z0-9]{86}', password_hash):
        raise ValueError('OpenSSL did not return a SHA-512 password hash')

    key_path = args.ssh_public_key
    if key_path is None:
        key_path = next((path for name in ('id_ed25519.pub', 'id_ecdsa.pub', 'id_rsa.pub')
                         if (path := Path.home() / '.ssh' / name).is_file()), None)
    public_key = None
    if key_path:
        # Copy just the type and public blob. Never read a private key.
        match = re.fullmatch(r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) '
                             r'([A-Za-z0-9+/]+={0,2})(?: [^\r\n]*)?', key_path.read_text().strip())
        if not match:
            raise ValueError(f'Expected one OpenSSH public key in {key_path}')
        run('ssh-keygen', '-lf', key_path, stdout=subprocess.DEVNULL)
        public_key = ' '.join(match.groups())
    return {'password_hash': password_hash, 'first_boot': first_boot(args, public_key)}


def make_image(archive, settings, output, builder):
    if builder:
        command = ssh_command(builder, 'python3', '-c', IMAGE_WORKER.read_text())
    else:
        if sys.platform != 'linux':
            raise ValueError('Use --builder with a Linux SSH host to prepare images from macOS')
        command = [sys.executable, str(IMAGE_WORKER)]
    with archive.open('rb') as source, subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output) as worker:
        try:
            worker.stdin.write(json.dumps(settings).encode() + b'\n')
            shutil.copyfileobj(source, worker.stdin)
            worker.stdin.close()
        except BrokenPipeError:
            pass
        if worker.wait():
            raise ValueError('Could not prepare the ImmortalWrt image on the Linux builder')


def make_profile_image(args, files, settings, output):
    imagebuilder = verified_download(f'{DOWNLOADS}/{RELEASE}/targets/x86/64/{IMAGEBUILDER}',
                                    args.image_dir, IMAGEBUILDER,
                                    'b9b290f5ef60a22bccd5bdca9c1e7523b8fc84e60462afbf550e20db94acf2c6')
    apk = verified_download(GITHUB_RELEASE + OPENCLASH_APK, args.image_dir, OPENCLASH_APK,
                            'f7ebbd43f9be15c5e6df26e5d0c03d50d0bb8f7fa4cc0d2c2bf048b08c0b155b')
    flags = (args.firmware, 'yes' if args.include_converter else 'no')
    command = (ssh_command(args.builder, 'bash', '-c', OPENCLASH_WORKER.read_text(),
                           'build-immortalwrt', *flags) if args.builder else
               ['bash', str(OPENCLASH_WORKER), *flags])
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output) as worker:
        try:
            with tarfile.open(fileobj=worker.stdin, mode='w|') as bundle:
                bundle.add(imagebuilder, IMAGEBUILDER)
                bundle.add(apk, OPENCLASH_APK)
                add_file(bundle, 'Dockerfile', BUILDER_DOCKERFILE.read_bytes())
                add_file(bundle, IMAGE_WORKER.name, IMAGE_WORKER.read_bytes())
                add_file(bundle, 'settings.json', json.dumps(settings).encode() + b'\n')
                if args.include_converter:
                    add_file(bundle, 'files/etc/init.d/router-subconverter', SUBCONVERTER_INIT.read_bytes(), 0o755)
                    dockerd = {
                        'data-root': '/overlay/docker', 'storage-driver': 'overlay2',
                        'features': {'containerd-snapshotter': False},
                        'bridge': 'none', 'ip-forward-no-drop': True,
                        'log-driver': 'local', 'log-level': 'warn',
                    }
                    add_file(bundle, 'files/etc/docker/router-profile.json', json.dumps(dockerd).encode())
                    add_file(bundle, 'files/etc/config/dockerd',
                             b"config globals 'globals'\n option alt_config_file '/etc/docker/router-profile.json'\n")
                for path, (contents, mode) in files.items():
                    add_file(bundle, f'files/{path}', contents, mode)
            worker.stdin.close()
        except BrokenPipeError:
            pass
        if worker.wait() or not output.tell():
            raise ValueError('Could not build an ImmortalWrt image with the OpenClash profile')


def prepare(args, write_image):
    output = args.output
    sidecar = output.with_suffix(output.suffix + '.sha256')
    if output.exists() or sidecar.exists():
        raise ValueError(f'The image or its checksum already exists: {output}')
    with TemporaryDirectory(prefix='.immortalwrt-', dir=output.parent) as stage:
        pending = Path(stage) / output.name
        with pending.open('w+b') as image:
            write_image(image)
            image.seek(0)
            digest = checksum(image)
        with sidecar.open('x') as handle:
            try:
                handle.write(digest + '\n')
                handle.flush()
                os.link(pending, output)
            except OSError:
                sidecar.unlink()
                raise
    print(output)


def provision(args, write_image):
    network = []
    if args.isolated:
        options = ['user', 'id=immortallan', 'restrict=on', f'net={args.lan.network}']
        if args.ssh_port:
            options.append(f'hostfwd=tcp:127.0.0.1:{args.ssh_port}-{args.lan.ip}:22')
        if args.web_port:
            options.append(f'hostfwd=tcp:127.0.0.1:{args.web_port}-{args.lan.ip}:80')
        devices = f'-netdev {",".join(options)} -device e1000,netdev=immortallan'
        if args.router_profile:
            wan = IPv4Network('10.0.2.0/24')
            if wan.overlaps(args.lan.network):
                wan = IPv4Network('172.31.254.0/24')
            if wan.overlaps(args.lan.network):
                raise ValueError('Choose a LAN subnet that does not overlap the isolated WAN')
            devices += f' -netdev user,id=immortalwan,restrict=on,net={wan} -device e1000,netdev=immortalwan'
        network = ['--args', devices]
    else:
        network = ['--net0', f'e1000,bridge={args.lan_bridge}']
        if args.wan_bridge:
            network.extend(('--net1', f'e1000,bridge={args.wan_bridge}'))
    with TemporaryDirectory(prefix='immortalwrt-') as stage:
        with (Path(stage) / 'disk.img').open('w+b') as image:
            write_image(image)
            image.seek(0)
            digest = checksum(image)
            image.seek(0)
            run(*ssh_command(args.proxmox, 'bash', '-c', PROXMOX_WORKER.read_text(), 'provision-immortalwrt',
                             str(args.vmid), args.hostname, args.storage, args.firmware, digest, *network),
                stdin=image)
    print(f'VM {args.vmid} started. LAN management address: http://{args.lan.ip}/')


def usb_info(device):
    """Return the target path, capacity, and logical sector size."""
    if sys.platform == 'darwin':
        if not re.fullmatch(r'/dev/disk[0-9]+', device):
            raise ValueError('Specify a whole macOS disk such as /dev/disk5')
        info = plistlib.loads(run('diskutil', 'info', '-plist', device, capture_output=True).stdout)
        if not (info.get('WholeDisk') and info.get('Internal') is False and info.get('BusProtocol') == 'USB'):
            raise ValueError('The target must be a whole external USB disk')
        return '/dev/r' + info['DeviceIdentifier'], info['Size'], info['DeviceBlockSize']
    if sys.platform == 'linux':
        if not re.fullmatch(r'/dev/sd[a-z]+', device):
            raise ValueError('Specify a whole Linux USB disk such as /dev/sdb')
        result = run('lsblk', '--json', '--tree', '--bytes', '--output',
                     'PATH,TYPE,TRAN,RM,RO,SIZE,LOG-SEC,MOUNTPOINTS', device, capture_output=True)
        disks = json.loads(result.stdout)['blockdevices']
        if len(disks) != 1:
            raise ValueError('Expected one whole USB disk')
        disk = disks[0]
        if not (disk['path'] == device and disk['type'] == 'disk' and disk['tran'] == 'usb'
                and disk['rm'] and not disk['ro']):
            raise ValueError('The target must be a writable removable USB disk')
        partitions = disk.get('children', [])
        if any(any(entry.get('mountpoints') or []) for entry in [disk, *partitions]):
            raise ValueError('Unmount the USB and deactivate any swap before writing')
        if any(part['type'] != 'part' or part.get('children') for part in partitions):
            raise ValueError('The USB contains active mapped devices')
        return device, disk['size'], disk['log-sec']
    raise ValueError('USB writing is supported on macOS and Linux')


def flash_usb(args):
    if os.geteuid() != 0:
        raise ValueError('Use sudo for the usb command')
    path = args.image
    expected = path.with_suffix(path.suffix + '.sha256').read_text().strip()
    with path.open('rb') as image:
        info = os.fstat(image.fileno())
        if not stat.S_ISREG(info.st_mode) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Use the raw .img and checksum produced by prepare')
        length = info.st_size
        if not length or checksum(image) != expected:
            raise ValueError('Prepared image failed its SHA-256 check')
        raw, capacity, sector = usb_info(args.device)
        if length > capacity or length % sector:
            raise ValueError('The USB disk capacity or sector size is incompatible with this image')
        identity = os.stat(raw).st_rdev
        if sys.platform == 'darwin':
            run('diskutil', 'unmountDisk', args.device)
        if usb_info(args.device) != (raw, capacity, sector):
            raise ValueError('USB disk changed during preparation')
        flags = os.O_RDWR | os.O_NOFOLLOW
        if sys.platform == 'linux':
            flags |= os.O_EXCL
        with os.fdopen(os.open(raw, flags), 'r+b') as target:
            device = os.fstat(target.fileno())
            is_disk = stat.S_ISBLK if sys.platform == 'linux' else stat.S_ISCHR
            if not is_disk(device.st_mode) or device.st_rdev != identity:
                raise ValueError('USB disk changed before writing')
            print(f'Writing {length} bytes to {args.device}. Keep it connected.', flush=True)
            image.seek(0)
            shutil.copyfileobj(image, target, CHUNK_SIZE)
            target.flush()
            os.fsync(target.fileno())
            target.seek(0)
            if checksum(target, length) != expected:
                raise ValueError('USB read-back failed its SHA-256 check')
    print(f'USB image verified on {args.device}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    download = commands.add_parser('download', help='save the verified official firmware')
    export = commands.add_parser('profile', help='save a portable router profile from an offline configuration archive')
    export.add_argument('--from-backup', type=Path, required=True, help='existing configuration archive')
    export.add_argument('--output', type=Path, required=True, help='new private profile archive')
    prepare_command = commands.add_parser('prepare', help='make a configured bootable raw image')
    proxmox = commands.add_parser('proxmox', help='create and start a new Proxmox VM')
    usb = commands.add_parser('usb', help='write a prepared image to a removable USB disk')
    for command in (download, prepare_command, proxmox):
        command.add_argument('--release', default=RELEASE)
        command.add_argument('--firmware', choices=('uefi', 'bios'), default='uefi')
        command.add_argument('--image-dir', type=Path, default=(
            ARCHIVE if ARCHIVE.is_dir() else Path.home() / '.cache' / 'immortalwrt'),
            help='directory for verified upstream downloads')
    for command in (prepare_command, proxmox):
        command.add_argument('--builder', help='Linux SSH builder with image tools, or Docker for OpenClash')
        command.add_argument('--router-profile', type=Path, help='private router profile archive with OpenClash settings')
        command.add_argument('--hostname', help='override the saved hostname (stock default immortalwrt)')
        command.add_argument('--lan', type=IPv4Interface, help='override the saved LAN address/prefix (stock default 192.168.1.1/24)')
        command.add_argument('--no-dhcp', action='store_true', help='disable LAN DHCP and router advertisements')
        command.add_argument('--zone', help='override IANA time zone (stock default Asia/Shanghai)')
        command.add_argument('--timezone', help='override POSIX time zone (stock default CST-8)')
        command.add_argument('--ssh-public-key', type=Path, help='override the public key discovered in ~/.ssh')
        command.add_argument('--password-file', type=Path, help='read the root password from a private file')
    prepare_command.add_argument('--output', type=Path, required=True, help='new .img file')
    proxmox.add_argument('--proxmox', default='pve', help='Proxmox root SSH destination (default pve)')
    proxmox.add_argument('--vmid', type=int, required=True)
    proxmox.add_argument('--storage', default='local-lvm')
    lan = proxmox.add_mutually_exclusive_group(required=True)
    lan.add_argument('--lan-bridge', help='Proxmox bridge for the router LAN')
    lan.add_argument('--isolated', action='store_true', help='use a private QEMU network for testing')
    proxmox.add_argument('--wan-bridge', help='separate Proxmox bridge for the router WAN')
    proxmox.add_argument('--ssh-port', type=int, help='isolated SSH forward on Proxmox loopback')
    proxmox.add_argument('--web-port', type=int, help='isolated HTTP forward on Proxmox loopback')
    usb.add_argument('--image', type=Path, required=True, help='raw image from the prepare command')
    usb.add_argument('--erase', dest='device', required=True, help='whole USB disk to erase, such as /dev/disk5')
    args = parser.parse_args()

    if args.command == 'usb':
        flash_usb(args)
        return
    if args.command == 'profile':
        write_profile(args.from_backup, args.output)
        print(args.output)
        return
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.release):
        parser.error('--release must be a numbered stable release, such as 25.12.2')
    if args.command == 'download':
        print(download_image(args.release, args.firmware, args.image_dir))
        return
    files = None
    if args.router_profile:
        if args.release != RELEASE:
            parser.error(f'--router-profile supports ImmortalWrt {RELEASE}')
        if not args.builder and sys.platform != 'linux':
            parser.error('OpenClash image builds on macOS require --builder with an x86-64 Linux Docker host')
        files = render_profile(load_profile(args.router_profile), args)
    else:
        args.hostname = args.hostname or 'immortalwrt'
        args.lan = args.lan or IPv4Interface('192.168.1.1/24')
        args.zone = args.zone or 'Asia/Shanghai'
        args.timezone = args.timezone or 'CST-8'
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', args.hostname):
        parser.error('--hostname must be a single DNS label')
    if args.lan.ip in (args.lan.network.network_address, args.lan.network.broadcast_address):
        parser.error('--lan must be a usable host address within its subnet')
    if args.builder and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*', args.builder):
        parser.error('Invalid Linux builder SSH destination')
    if args.command == 'prepare' and args.output.suffix != '.img':
        parser.error('--output must end in .img')
    if args.command == 'proxmox':
        if not 100 <= args.vmid <= 999999999:
            parser.error('--vmid must be between 100 and 999999999')
        for value in (args.proxmox, args.storage, args.lan_bridge, args.wan_bridge):
            if value is not None and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*', value):
                parser.error('Invalid Proxmox SSH destination, bridge, or storage name')
        if args.wan_bridge and (args.isolated or args.lan_bridge == args.wan_bridge):
            parser.error('--wan-bridge must be separate from --lan-bridge')
        if args.ssh_port is not None or args.web_port is not None:
            if not args.isolated or any(port is not None and not 1024 <= port <= 65535
                                        for port in (args.ssh_port, args.web_port)):
                parser.error('Use loopback ports 1024–65535 with --isolated')
            if args.ssh_port == args.web_port:
                parser.error('SSH and HTTP require different loopback ports')

    if files is not None:
        write_image = partial(make_profile_image, args, files, image_settings(args))
    else:
        archive = download_image(args.release, args.firmware, args.image_dir)
        builder = args.builder or getattr(args, 'proxmox', None)
        write_image = partial(make_image, archive, image_settings(args), builder=builder)
    if args.command == 'prepare':
        prepare(args, write_image)
    else:
        provision(args, write_image)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
