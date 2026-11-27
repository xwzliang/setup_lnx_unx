"""Edit the local trusted browser login in the Home Assistant Core container."""

import ipaddress
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import uuid

import yaml
from yaml.nodes import MappingNode, ScalarNode


BEGIN = "# BEGIN installer trusted web login"
END = "# END installer trusted web login"


def field(node, name):
    return next((value for key, value in node.value if key.value == name), None)


def trusted_config(source, address, owner_id):
    network = ipaddress.IPv4Interface(address).network
    private_lans = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(network.subnet_of(ipaddress.IPv4Network(lan)) for lan in private_lans):
        raise ValueError("Trusted browser login requires a private IPv4 LAN subnet.")
    owner = uuid.UUID(owner_id)
    if owner.version != 4:
        raise ValueError("Expected a Home Assistant owner ID.")

    root = yaml.compose(source)
    if root is not None and (not isinstance(root, MappingNode) or root.flow_style):
        raise ValueError("Expected a block mapping in configuration.yaml.")
    section = field(root, "homeassistant") if root is not None else None
    lines = source.splitlines(keepends=True)
    indent = 2
    if section is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.extend(["\n", "homeassistant:\n"])
        start = end = len(lines)
    elif isinstance(section, ScalarNode) and section.tag == "tag:yaml.org,2002:null" and not section.value:
        start = end = section.start_mark.line + 1
    elif isinstance(section, MappingNode) and not section.flow_style:
        start = end = section.start_mark.line
        indent = section.start_mark.column
        if field(section, "auth_providers") is not None:
            markers = {marker: [i for i, line in enumerate(lines) if line.rstrip() == " " * indent + marker]
                       for marker in (BEGIN, END)}
            if len(markers[BEGIN]) != 1 or len(markers[END]) != 1:
                raise ValueError("Home Assistant already has a custom auth_providers configuration.")
            start, end = markers[BEGIN][0], markers[END][0] + 1
            if not start < field(section, "auth_providers").start_mark.line < end:
                raise ValueError("Could not locate the installer's trusted login configuration.")
    else:
        raise ValueError("Home Assistant configuration must use a block mapping for homeassistant.")

    block = [BEGIN, "auth_providers:", "  - type: trusted_networks", "    trusted_networks:",
             f'      - "{network}"', "    trusted_users:", f'      "{network}": "{owner.hex}"',
             "    allow_bypass_login: true", "  - type: homeassistant", END]
    lines[start:end] = [" " * indent + line + "\n" for line in block]
    return "".join(lines)


def replace_file(path, content, mode):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def main(address, owner_id):
    path = Path("/config/configuration.yaml")
    if path.is_symlink():
        raise ValueError("Expected configuration.yaml to be a regular file.")
    original = path.read_bytes()
    updated = trusted_config(original.decode(), address, owner_id).encode()
    if updated == original:
        print("unchanged", ipaddress.IPv4Interface(address).network)
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    replace_file(path, updated, mode)
    try:
        subprocess.run([sys.executable, "-m", "homeassistant", "--script", "check_config", "--config", "/config"],
                       check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        replace_file(path, original, mode)
        raise ValueError("Home Assistant rejected the updated configuration. The original file was restored.") from None
    print("changed", ipaddress.IPv4Interface(address).network)


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (ValueError, yaml.YAMLError) as error:
        sys.exit(str(error) if isinstance(error, ValueError) else "Could not parse configuration.yaml.")
