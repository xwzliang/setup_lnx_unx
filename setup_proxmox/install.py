#!/usr/bin/env python3
"""Build a machine-specific, unattended Proxmox VE installer ISO."""

import argparse
import base64
import getpass
import hashlib
import ipaddress
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ISO_NAME = 'proxmox-ve_9.3-1.iso'
ISO_URL = f'https://download.proxmox.com/iso/{ISO_NAME}'
ISO_SHA256 = 'cc4fc97b9ac3a5712ad5b665195753571923a18e11f5c2ebb113fdc29a50bd36'
ASSISTANT = 'proxmox-auto-install-assistant'
DISK_PROPERTIES = {'ID_SERIAL', 'ID_SERIAL_SHORT', 'ID_WWN', 'ID_WWN_WITH_EXTENSION'}
VM_HARDWARE = Path.home() / '.config/setup-proxmox/vm-hardware.json'
VM_SETUP_FILES = (
    'setup_proxmox/install.py', 'setup_proxmox/create_vms.py', 'setup_proxmox/vm_profiles.json',
    'setup_proxmox/first_boot_vms.py', 'setup_proxmox/setup-proxmox-vms.service',
    'setup_homeassistant/install.mjs', 'setup_homeassistant/install-extras.mjs',
    'setup_homeassistant/trusted-web-login.py', 'setup_homeassistant/provision-proxmox.sh',
    'setup_openmediavault/install.py', 'setup_openmediavault/provision.sh',
    'setup_openmediavault/bootstrap.sh', 'setup_openmediavault/configure_guest.py',
    'packages/samba/scripts/linux/setup_omv_smb_aio.py',
)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def read_object(value, name, fields):
    if not isinstance(value, dict) or value.keys() - fields:
        raise ValueError(f'Invalid or unknown fields in {name}')
    return value


def match(value, pattern, name):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'Invalid or missing {name}')
    return value


def load_vm_setup(value):
    if value is None:
        return None
    options = read_object(value, 'vm_setup', {
        'profiles', 'media_url', 'omv_data_gb', 'xiaomi_home', 'trusted_web_login',
    })
    catalog = json.loads((HERE / 'vm_profiles.json').read_text())
    profiles = options.get('profiles', list(catalog['vms']))
    if (not isinstance(profiles, list) or not profiles
            or not all(isinstance(name, str) and name in catalog['vms'] for name in profiles)
            or len(profiles) != len(set(profiles))):
        raise ValueError('Select a nonempty list of distinct VM profile names')
    media_url = options.get('media_url')
    if media_url is not None:
        if not isinstance(media_url, str):
            raise ValueError('Use an HTTP(S) base URL for vm_setup.media_url')
        url = urlsplit(media_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.query or url.fragment):
            raise ValueError('Use an HTTP(S) base URL without credentials for vm_setup.media_url')
        media_url = media_url.rstrip('/') + '/'
    for name in profiles:
        if name == 'omv':
            continue
        for drive in catalog['vms'][name]['media'].values():
            if 'image' in drive and 'url' not in catalog['media'][drive['image']] and media_url is None:
                raise ValueError(f'vm_setup.media_url is required to supply the {name} installer media')
    size = options.get('omv_data_gb', 32)
    if type(size) is not int or not (size == 0 or 8 <= size <= 65536):
        raise ValueError('Use omv_data_gb = 0 or a size from 8 to 65536 GiB')
    booleans = {key: options.get(key, True) for key in ('xiaomi_home', 'trusted_web_login')}
    if not all(isinstance(value, bool) for value in booleans.values()):
        raise ValueError('Use boolean Xiaomi Home and trusted web login settings')
    return {'profiles': profiles, 'media_url': media_url, 'omv_data_gb': size, **booleans}


def load_profile(path):
    profile = read_object(json.loads(path.read_text()), 'profile', {
        'fqdn', 'email', 'country', 'keyboard', 'timezone', 'network', 'disk', 'repository', 'upgrade', 'vm_setup',
    })
    label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    fqdn = match(profile.get('fqdn'), rf'{label}(?:\.{label})+', 'fqdn').lower()
    if len(fqdn) > 253:
        raise ValueError('The FQDN is too long')
    email = match(profile.get('email'), r'[^\s@]+@[^\s@]+\.[^\s@]+', 'admin email')
    country = match(profile.get('country', 'cn'), r'[a-z]{2}', 'country')
    keyboard = match(profile.get('keyboard', 'en-us'), r'[a-z0-9-]+', 'keyboard')
    timezone = match(profile.get('timezone', 'Asia/Shanghai'), r'[A-Za-z0-9_+/-]+', 'timezone')
    network = read_object(profile.get('network'), 'network', {'cidr', 'gateway', 'dns', 'mac'})
    cidr = ipaddress.IPv4Interface(match(network.get('cidr'), r'[^/]+/[0-9]+', 'network CIDR'))
    gateway = ipaddress.IPv4Address(match(network.get('gateway'), r'[0-9.]+', 'gateway'))
    dns = ipaddress.IPv4Address(match(network.get('dns'), r'[0-9.]+', 'DNS server'))
    reserved = (cidr.network.network_address, cidr.network.broadcast_address)
    if gateway not in cidr.network or gateway == cidr.ip or gateway in reserved or cidr.ip in reserved:
        raise ValueError('Use distinct, usable host and gateway addresses on the management subnet')
    mac = match(network.get('mac'), r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', 'management NIC MAC').lower()
    if mac == '00:00:00:00:00:00' or int(mac[:2], 16) & 1:
        raise ValueError('Use the physical Ethernet port’s unicast MAC address')
    disk = read_object(profile.get('disk'), 'disk', {'property', 'id'})
    property_name = disk.get('property', 'ID_SERIAL_SHORT')
    if not isinstance(property_name, str) or property_name not in DISK_PROPERTIES:
        raise ValueError('Select the target disk by its exact udev serial number or WWN')
    identifier = match(disk.get('id'), r'[0-9A-Za-z][0-9A-Za-z_.:+-]{3,127}', 'disk serial or WWN')
    if identifier == 'REPLACE-WITH-EXACT-DISK-SERIAL':
        raise ValueError('Replace the example disk serial with the target disk’s exact ID')
    repository = profile.get('repository', 'enterprise')
    upgrade = profile.get('upgrade', False)
    if repository not in ('enterprise', 'no-subscription') or not isinstance(upgrade, bool):
        raise ValueError('Use enterprise or no-subscription, and a boolean upgrade setting')
    return {
        'fqdn': fqdn, 'email': email, 'country': country, 'keyboard': keyboard, 'timezone': timezone,
        'cidr': str(cidr), 'gateway': str(gateway), 'dns': str(dns), 'mac': mac,
        'disk_property': property_name, 'disk_id': identifier, 'repository': repository, 'upgrade': upgrade,
        'vm_setup': load_vm_setup(profile.get('vm_setup')),
    }


def password_hash(path):
    if path:
        password = path.read_text().rstrip('\r\n')
    else:
        if not sys.stdin.isatty():
            raise ValueError('Use --password-file when building without an interactive terminal')
        password = getpass.getpass('New Proxmox root password: ')
        if password != getpass.getpass('Confirm root password: '):
            raise ValueError('The passwords did not match')
    if len(password) < 8 or any(char in password for char in '\r\n\0'):
        raise ValueError('Use a single-line root password with at least eight characters')
    hashed = run('openssl', 'passwd', '-6', '-stdin', input=password + '\n',
                 capture_output=True, text=True).stdout.strip()
    return match(hashed, r'\$6\$[./A-Za-z0-9]+\$[./A-Za-z0-9]{86}', 'SHA-512 password hash')


def ssh_key(path):
    if path is None:
        directory = Path.home() / '.ssh'
        path = next((directory / name for name in ('id_ed25519.pub', 'id_ecdsa.pub', 'id_rsa.pub')
                     if (directory / name).is_file()), None)
    if path is None:
        return None
    key = path.read_text().strip().split()
    if len(key) < 2 or not re.fullmatch(r'ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)', key[0]):
        raise ValueError('Provide a supported OpenSSH public key')
    run('ssh-keygen', '-l', '-f', path, stdout=subprocess.DEVNULL)
    return ' '.join(key[:2])


def answer_file(profile, hashed, key):
    quote = json.dumps
    fields = {
        'fqdn': profile['fqdn'], 'mailto': profile['email'], 'root-password-hashed': hashed,
        'country': profile['country'], 'keyboard': profile['keyboard'], 'timezone': profile['timezone'],
    }
    lines = ['[global]', *(f'{name} = {quote(value)}' for name, value in fields.items())]
    if key:
        lines.append(f'root-ssh-keys = {quote([key])}')
    lines.extend(['', '[network]', 'source = "from-answer"',
                  *(f'{name} = {quote(profile[name])}' for name in ('cidr', 'gateway', 'dns')),
                  f'filter.ID_NET_NAME_MAC = "enx{profile["mac"].replace(":", "")}"',
                  '', '[disk-setup]', 'filesystem = "ext4"',
                  f'filter.{profile["disk_property"]} = {quote(profile["disk_id"])}',
                  '', '[first-boot]', 'source = "from-iso"', ''])
    return '\n'.join(lines)


def vm_setup_payload(options, key, hardware_file):
    from create_vms import CreateError, private_settings

    if {'ha', 'omv'}.intersection(options['profiles']) and key is None:
        raise ValueError('VM setup needs an OpenSSH public key. Use --ssh-public-key.')
    files = {name: (HERE.parent / name).read_bytes() for name in VM_SETUP_FILES}
    job = {**options, 'tag': f'setup-vms-{secrets.token_hex(8)}'}
    files['vm-job.json'] = json.dumps(job).encode()
    if key:
        files['ssh.pub'] = (key + '\n').encode()
    if 'mac' in options['profiles']:
        args = SimpleNamespace(hardware_file=hardware_file, with_passthrough=False)
        try:
            read = private_settings([{'profile': 'mac', 'private_args': True}], args)
        except CreateError as error:
            raise ValueError(str(error)) from None
        files['vm-hardware.json'] = json.dumps(read).encode()
    with BytesIO() as output:
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, data in files.items():
                item = tarfile.TarInfo(name)
                item.mode = 0o600
                item.size = len(data)
                archive.addfile(item, BytesIO(data))
        return base64.encodebytes(output.getvalue()).decode()


def first_boot_script(profile, key=None, hardware_file=VM_HARDWARE):
    source = (HERE / 'first_boot.sh').read_text()
    shebang, body = source.split('\n', 1)
    options = shlex.join([profile['repository'], str(profile['upgrade']).lower()])
    hook = ''
    if profile.get('vm_setup') is not None:
        payload = vm_setup_payload(profile['vm_setup'], key, hardware_file)
        hook = f"""queue_vm_setup() {{
    local job=/var/lib/setup-proxmox/vm-setup
    install -d -m 0700 "$job"
    base64 -d <<'SETUP_VM_PAYLOAD' | tar -xzf - -C "$job"
{payload}SETUP_VM_PAYLOAD
    install -m 0644 "$job/setup_proxmox/setup-proxmox-vms.service" /etc/systemd/system/setup-proxmox-vms.service
    systemctl daemon-reload
    systemctl enable --now --no-block setup-proxmox-vms.service
}}
"""
    return f'{shebang}\nset -- {options}\n{hook}{body}'


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 ** 2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stock_iso(path, cache):
    if path is None:
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / ISO_NAME
        if not path.exists():
            with TemporaryDirectory(prefix='.download-', dir=cache) as temporary:
                pending = Path(temporary) / ISO_NAME
                run('curl', '--fail', '--location', '--silent', '--show-error', '--retry', '2',
                    '--proto', '=https', '--proto-redir', '=https', '--output', pending, ISO_URL)
                if checksum(pending) != ISO_SHA256:
                    raise ValueError('Downloaded ISO failed the published SHA-256 check')
                pending.replace(path)
    if checksum(path) != ISO_SHA256:
        raise ValueError(f'{path} failed the published SHA-256 check for {ISO_NAME}')
    return path.resolve()


def build_iso(stock, stage, native):
    if native:
        base = [ASSISTANT]
        source = stock
        work = stage
    else:
        dockerfile = (HERE / 'Dockerfile').read_bytes()
        tag = 'setup-proxmox-iso:' + hashlib.sha256(dockerfile).hexdigest()[:12]
        found = subprocess.run(['docker', 'image', 'inspect', tag],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if found.returncode:
            run('docker', 'build', '--platform', 'linux/amd64', '-t', tag, '-', input=dockerfile)
        base = ['docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/amd64',
                '--user', f'{os.getuid()}:{os.getgid()}',
                '--volume', f'{stock}:/input.iso:ro', '--volume', f'{stage}:/work', tag, ASSISTANT]
        source = Path('/input.iso')
        work = Path('/work')
    run(*base, 'validate-answer', work / 'answer.toml')
    run(*base, 'prepare-iso', '--fetch-from', 'iso', '--answer-file', work / 'answer.toml',
        '--on-first-boot', work / 'first-boot.sh', '--tmp', work, '--output', work / 'installer.iso', source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True, help='machine settings JSON')
    parser.add_argument('--output', type=Path, required=True, help='new private installer ISO')
    parser.add_argument('--stock-iso', type=Path, help=f'local stock {ISO_NAME}; verified before use')
    parser.add_argument('--cache-dir', type=Path, default=Path.home() / '.cache' / 'proxmox-iso')
    parser.add_argument('--password-file', type=Path, help='read the root password from a private file')
    parser.add_argument('--ssh-public-key', type=Path, help='override the public key discovered in ~/.ssh')
    parser.add_argument('--vm-hardware-file', type=Path, default=VM_HARDWARE,
                        help='private QEMU settings for the Mac profile, when selected')
    parser.add_argument('--native', action='store_true', help='use an installed Proxmox assistant instead of Docker')
    args = parser.parse_args()
    output = args.output.resolve()
    sidecar = output.with_suffix('.iso.sha256')
    if output.suffix != '.iso' or output.exists() or sidecar.exists():
        parser.error('--output must end in .iso and both the ISO and checksum must be new files')
    if not output.parent.is_dir():
        parser.error('Create the destination directory before building')
    if not shutil.which(ASSISTANT if args.native else 'docker'):
        parser.error('Install Docker or use --native with the Proxmox auto-install assistant')

    profile = load_profile(args.profile)
    key = ssh_key(args.ssh_public_key)
    hook_text = first_boot_script(profile, key, args.vm_hardware_file)
    hashed = password_hash(args.password_file)
    stock = stock_iso(args.stock_iso, args.cache_dir)
    with TemporaryDirectory(prefix='.proxmox-iso-', dir=output.parent) as temporary:
        stage = Path(temporary)
        (stage / 'answer.toml').write_text(answer_file(profile, hashed, key))
        hook = stage / 'first-boot.sh'
        hook.write_text(hook_text)
        hook.chmod(0o700)
        build_iso(stock, stage, args.native)
        installer = stage / 'installer.iso'
        installer.chmod(0o600)
        digest = checksum(installer)
        with sidecar.open('x') as handle:
            try:
                handle.write(f'{digest}  {output.name}\n')
                handle.flush()
                os.link(installer, output)
            except OSError:
                sidecar.unlink()
                raise
    print(f'Prepared {output}')
    print(f'Boot the intended node from this ISO. Management URL: https://{profile["cidr"].split("/")[0]}:8006/')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
