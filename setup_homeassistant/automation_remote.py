"""Run inside the HAOS SSH add-on to read or deploy the managed YAML."""

import fcntl
from http.client import HTTPException
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.request import Request, urlopen

CONFIG = Path("/config")
AUTOMATIONS = "automations.yaml"
XIAOMI = "packages/xiaomi_home_auto_refresh.yaml"
MANAGED = (AUTOMATIONS, XIAOMI)


class DeployError(Exception):
    pass


def decode_bundle(raw):
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) != set(MANAGED)
            or not all(isinstance(value, str) for value in data.values())):
        raise ValueError("Expected the two managed Home Assistant YAML files.")
    return data


def read_managed():
    if (CONFIG / "packages").is_symlink():
        raise DeployError("Expected packages to be a real configuration directory.")
    for name in MANAGED:
        path = CONFIG / name
        if path.is_symlink() or not path.is_file():
            raise DeployError(f"Expected a regular configuration file at {name}.")
    return {name: (CONFIG / name).read_bytes().decode("utf-8") for name in MANAGED}


def check_layout():
    import yaml
    from yaml.nodes import MappingNode, ScalarNode

    def field(node, name):
        matches = [value for key, value in node.value if key.value == name] if isinstance(node, MappingNode) else []
        return matches[0] if len(matches) == 1 else None

    config = yaml.compose((CONFIG / "configuration.yaml").read_text())
    automation = field(config, "automation")
    packages = field(field(config, "homeassistant"), "packages")
    if not (isinstance(automation, ScalarNode) and automation.tag == "!include"
            and automation.value == AUTOMATIONS and isinstance(packages, ScalarNode)
            and packages.tag == "!include_dir_named" and packages.value == "packages"):
        raise DeployError("Home Assistant no longer includes the managed automation files.")


def validate_yaml(data):
    import yaml
    from yaml.nodes import MappingNode, ScalarNode, SequenceNode

    def mapping(node):
        if not isinstance(node, MappingNode) or not all(isinstance(key, ScalarNode) for key, _ in node.value):
            raise DeployError("Expected a YAML mapping in the managed automation files.")
        fields = {key.value: value for key, value in node.value}
        if len(fields) != len(node.value):
            raise DeployError("Duplicate YAML mapping keys in the managed automation files.")
        return fields

    try:
        package = mapping(yaml.compose(data[XIAOMI]))
        if set(package) != {"automation", "shell_command"}:
            raise DeployError("The Xiaomi package must contain automation and shell_command sections.")
        mapping(package["shell_command"])
        ids = set()
        for name, entries in [(AUTOMATIONS, yaml.compose(data[AUTOMATIONS])), (XIAOMI, package["automation"])]:
            if not isinstance(entries, SequenceNode):
                raise DeployError(f"Expected an automation list in {name}.")
            for entry in entries.value:
                identifier = mapping(entry).get("id")
                if identifier is not None:
                    if (not isinstance(identifier, ScalarNode) or not identifier.value
                            or identifier.value in ids):
                        raise DeployError(f"Empty or duplicate automation ID in {name}.")
                    ids.add(identifier.value)
    except yaml.YAMLError as error:
        line = getattr(error, "problem_mark", None)
        suffix = f" near line {line.line + 1}" if line is not None else ""
        raise DeployError(f"Invalid automation YAML{suffix}.") from None


def check_core():
    try:
        result = subprocess.run(
            ["ha", "core", "check", "--no-progress", "--raw-json"],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0 and json.loads(result.stdout).get("result") == "ok":
            return
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        pass
    raise DeployError("Home Assistant Core rejected the configuration. Inspect ha core check on the host.")


def reload_domain(domain):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise DeployError("No Supervisor token is available in the SSH login environment.")
    request = Request(
        f"http://supervisor/core/api/services/{domain}/reload",
        data=b"{}", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            response.read()
    except (OSError, URLError, HTTPException):
        raise DeployError(f"Home Assistant did not confirm {domain}.reload.") from None


def replace(path, text, metadata):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".automation-deploy-", delete=False) as stream:
        pending = Path(stream.name)
        try:
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def apply(data):
    validate_yaml(data)
    if read_managed() == data:
        return {"status": "unchanged"}
    directory = CONFIG / ".automation-deploy-backups"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise DeployError("Expected a private automation backup directory.")
    with (directory / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_layout()
        original = read_managed()
        changed = [name for name in MANAGED if data[name] != original[name]]
        if not changed:
            return {"status": "unchanged"}
        backup = Path(tempfile.mkdtemp(prefix="previous-", dir=directory))
        metadata = {}
        for name in changed:
            metadata[name] = (CONFIG / name).stat()
            path = backup / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(original[name])

        domains = ["shell_command", "automation"] if XIAOMI in changed else ["automation"]
        written = []
        reloading = False
        try:
            for name in changed:
                path = CONFIG / name
                if path.is_symlink() or path.read_bytes() != original[name].encode("utf-8"):
                    raise DeployError(f"{name} changed while deployment was in progress.")
                written.append(name)
                replace(path, data[name], metadata[name])
            check_core()
            if read_managed() != data:
                raise DeployError("The managed files changed during validation.")
            reloading = True
            for domain in domains:
                reload_domain(domain)
            if read_managed() != data:
                raise DeployError("The managed files changed during reload.")
        except (OSError, UnicodeError, DeployError) as error:
            rollback_failed = False
            for name in reversed(written):
                path = CONFIG / name
                try:
                    if path.is_symlink():
                        rollback_failed = True
                        continue
                    current = path.read_bytes().decode("utf-8")
                    if current == data[name]:
                        replace(path, original[name], metadata[name])
                    elif current != original[name]:
                        rollback_failed = True
                except (OSError, UnicodeError):
                    rollback_failed = True
            if reloading and not rollback_failed:
                try:
                    for domain in domains:
                        reload_domain(domain)
                except DeployError:
                    rollback_failed = True
            if rollback_failed:
                raise DeployError(f"Deployment interrupted by an error. Review the private backup at {backup}.") from None
            message = str(error) if isinstance(error, DeployError) else "Could not complete the deployment."
            raise DeployError(f"{message} Previous YAML restored from {backup}.") from None
    return {"status": "deployed", "changed": changed, "backup": str(backup)}


def interrupted(_signal, _frame):
    raise DeployError("Deployment interrupted.")


def main(command):
    import yaml

    os.umask(0o077)
    try:
        check_layout()
        if command == "snapshot":
            result = read_managed()
            validate_yaml(result)
        elif command == "check":
            validate_yaml(read_managed())
            check_core()
            result = {"status": "valid"}
        elif command == "deploy":
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, interrupted)
            result = apply(decode_bundle(sys.stdin.buffer.read()))
        else:
            raise DeployError("Unknown automation operation.")
    except (DeployError, OSError, ValueError, yaml.YAMLError) as error:
        detail = str(error) if isinstance(error, DeployError) else "Could not process the managed Home Assistant files."
        sys.exit(detail)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
