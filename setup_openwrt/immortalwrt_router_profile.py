"""Select and adapt saved router settings for a fresh firewall4 installation."""

from io import BytesIO
from ipaddress import IPv4Interface
from pathlib import PurePosixPath
import shlex
import tarfile
from urllib.parse import urlsplit

CONFIGS = ('network', 'dhcp', 'firewall', 'system', 'openclash')
CORE = 'etc/openclash/core/clash_meta'
IPV6 = 'etc/sysctl.d/90-openclash-killswitch.conf'
REQUIRED_FILES = (*[f'etc/config/{name}' for name in CONFIGS], CORE)
OPENCLASH_DIRS = {'config', 'custom', 'game_rules', 'history', 'proxy_provider',
                  'rule_provider', 'split-dns'}
OPENCLASH_DATA = {'ASN.mmdb', 'Country.mmdb', 'GeoIP.dat', 'GeoSite.dat', 'Model.bin',
                  'accelerated-domains.china.conf', 'china_ip_route.ipset', 'china_ip6_route.ipset'}
SERVICE_GUARD = """chain setup_service_guard {
 type filter hook prerouting priority -310; policy accept;
 iifname { "lo", "br-lan", "wireguard", "utun" } return
 fib daddr type != local return
 tcp dport { 22, 80, 81, 443, 444, 7681, 7788, 7789, 7874, 7890, 7892, 7893, 7895, 9090, 15051, 60000 } counter drop
 udp dport { 7788, 7789, 7874, 7892, 7893, 7895 } counter drop
}
"""


def profile_member(path):
    if path in REQUIRED_FILES or path == IPV6:
        return True
    parts = PurePosixPath(path).parts
    if parts[:2] != ('etc', 'openclash') or len(parts) < 3:
        return False
    if len(parts) == 3:
        return parts[2] in OPENCLASH_DATA or PurePosixPath(path).suffix in ('.yaml', '.yml')
    return parts[2] in OPENCLASH_DIRS


def load_profile(source):
    files = {}
    with tarfile.open(source, 'r:*') as archive:
        for entry in archive:
            path = entry.name
            while path.startswith('./'):
                path = path[2:]
            parts = PurePosixPath(path).parts
            if not entry.isfile() or path.startswith('/') or '..' in parts:
                continue
            path = '/'.join(parts)
            if profile_member(path):
                if path in files:
                    raise ValueError('Router profile contains duplicate file entries')
                mode = 0o700 if path == CORE or entry.mode & 0o100 else 0o600
                files[path] = (archive.extractfile(entry).read(), mode)
    for path in REQUIRED_FILES:
        if path not in files or not files[path][0]:
            raise ValueError(f'Router profile requires {path}')
    return files


def write_profile(source, output):
    files = load_profile(source)
    with output.open('xb') as handle, tarfile.open(fileobj=handle, mode='w:gz') as archive:
        for path, (contents, mode) in sorted(files.items()):
            add_file(archive, path, contents, mode)


def add_file(archive, path, contents, mode=0o600):
    entry = tarfile.TarInfo(path)
    entry.mode = mode
    entry.size = len(contents)
    archive.addfile(entry, BytesIO(contents))


def parse_uci(text):
    sections = []
    for line in text.splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        if tokens[0] == 'config' and len(tokens) in (2, 3):
            sections.append((tokens[1:], []))
        elif tokens[0] in ('option', 'list') and len(tokens) == 3 and sections:
            sections[-1][1].append(tokens)
        else:
            raise ValueError('Unsupported saved UCI syntax')
    return sections


def section(sections, kind, name=None):
    for head, options in sections:
        if head[0] == kind and (name is None or head[1:] == [name]):
            return options
    raise ValueError(f'Router profile is missing a {name or kind} section')


def value(options, name, default=None):
    return next((entry[2] for entry in reversed(options) if entry[1] == name), default)


def update(options, key, new_value=None):
    options[:] = [entry for entry in options if entry[1] != key]
    if new_value is not None:
        options.append(['option', key, new_value])


def render_profile(files, args):
    configs = {name: parse_uci(files[f'etc/config/{name}'][0].decode()) for name in CONFIGS}
    lan = section(configs['network'], 'interface', 'lan')
    ip = value(lan, 'ipaddr', '')
    if args.lan is None:
        if not ip:
            raise ValueError('The saved LAN has no IPv4 address. Pass --lan to set one')
        args.lan = IPv4Interface(ip if '/' in ip else f"{ip}/{value(lan, 'netmask', '255.255.255.0')}")
    system = section(configs['system'], 'system')
    args.hostname = args.hostname or value(system, 'hostname', 'immortalwrt')
    args.zone = args.zone or value(system, 'zonename', 'Asia/Shanghai')
    args.timezone = args.timezone or value(system, 'timezone', 'CST-8')
    configs['system'] = [(head, options) for head, options in configs['system']
                         if head[0] in ('system', 'timeserver')]

    # Use the new release's firewall4 and OpenClash runtime includes.
    configs['firewall'] = [(head, options) for head, options in configs['firewall']
                           if head[0] != 'include' and all(value(options, key) != 'docker'
                                                          for key in ('name', 'src', 'dest'))]
    defaults = section(configs['firewall'], 'defaults')
    update(defaults, 'fullcone')
    update(defaults, 'flow_offloading', '0')
    update(defaults, 'flow_offloading_hw', '0')
    configs['network'] = [(head, options) for head, options in configs['network']
                          if head != ['interface', 'docker'] and value(options, 'name') != 'docker0']
    dnsmasq = section(configs['dhcp'], 'dnsmasq')
    # Start with WAN DNS. OpenClash installs its DNS redirection when ready.
    update(dnsmasq, 'noresolv', '0')
    update(dnsmasq, 'resolvfile', '/tmp/resolv.conf.d/resolv.conf.auto')
    update(dnsmasq, 'server')

    clash = section(configs['openclash'], 'openclash', 'config')
    active = value(clash, 'config_path', '').lstrip('/')
    if not active.startswith('etc/openclash/config/') or active not in files:
        raise ValueError('Router profile is missing its active OpenClash subscription config')
    for key, setting in {'enable': '1', 'core_type': 'Meta', 'small_flash_memory': '0',
                         'auto_update': '0', 'servers_update': '0'}.items():
        update(clash, key, setting)
    args.include_converter = False
    for head, options in configs['openclash']:
        if head[0] != 'config_subscribe':
            continue
        url = urlsplit(value(options, 'convert_address', ''))
        if (url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', ip.split('/')[0])
                and url.port == 15051):
            update(options, 'convert_address', url._replace(netloc='127.0.0.1:15051').geturl())
            args.include_converter = True
    if getattr(args, 'isolated', False):
        wan = section(configs['network'], 'interface', 'wan')
        update(wan, 'proto', 'dhcp')
        update(wan, 'username')
        update(wan, 'password')
        for head, options in configs['network']:
            if head[0] == 'interface' and value(options, 'proto') == 'wireguard':
                update(options, 'auto', '0')

    rendered = dict(files)
    for name, sections in configs.items():
        data = '\n\n'.join(shlex.join(['config', *head]) + '\n' +
                           '\n'.join('\t' + shlex.join(entry) for entry in options)
                           for head, options in sections) + '\n'
        rendered[f'etc/config/{name}'] = (data.encode(), 0o600)
    rendered['etc/nftables.d/20-setup-service-guard.nft'] = (SERVICE_GUARD.encode(), 0o644)
    if IPV6 in rendered:
        data, _ = rendered[IPV6]
        for line in data.decode().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, _, setting = line.partition('=')
                if (key.strip() not in ('net.ipv6.conf.all.disable_ipv6', 'net.ipv6.conf.default.disable_ipv6')
                        or setting.strip() not in ('0', '1')):
                    raise ValueError('Unsupported IPv6 setting in router profile')
    return rendered
