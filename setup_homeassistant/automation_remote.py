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
ROOT_CONFIG = "configuration.yaml"
AUTOMATIONS = "automations.yaml"
XIAOMI = "packages/xiaomi_home_auto_refresh.yaml"
DISPLAY = "packages/macmini_display.yaml"
REQUIRED = (AUTOMATIONS, XIAOMI)
MANAGED = (*REQUIRED, DISPLAY)
DISPLAY_COMMANDS = {"macmini_connect_imac_display", "macmini_disconnect_imac_display"}


class DeployError(Exception):
    pass


def decode_bundle(raw):
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) not in (set(REQUIRED), set(MANAGED))
            or not all(isinstance(value, str) for value in data.values())):
        raise ValueError("Expected the managed Home Assistant automation YAML files.")
    return data


def read_file(name):
    path = CONFIG / name
    if not path.is_symlink():
        if path.is_file():
            return path.read_bytes().decode("utf-8")
        if name == DISPLAY and not path.exists():
            return None
    raise DeployError(f"Expected a regular configuration file at {name}.")


def read_managed():
    if (CONFIG / "packages").is_symlink():
        raise DeployError("Expected packages to be a real configuration directory.")
    return {name: value for name in MANAGED if (value := read_file(name)) is not None}


def check_layout():
    import yaml
    from yaml.nodes import MappingNode, ScalarNode

    def field(node, name):
        matches = [value for key, value in node.value if key.value == name] if isinstance(node, MappingNode) else []
        return matches[0] if len(matches) == 1 else None

    config = yaml.compose((CONFIG / ROOT_CONFIG).read_text())
    automation = field(config, "automation")
    packages = field(field(config, "homeassistant"), "packages")
    if not (isinstance(automation, ScalarNode) and automation.tag == "!include"
            and automation.value == AUTOMATIONS and isinstance(packages, ScalarNode)
            and packages.tag == "!include_dir_named" and packages.value == "packages"):
        raise DeployError("Home Assistant no longer includes the managed automation files.")


def validate_yaml(data):
    import yaml
    from yaml.nodes import MappingNode, ScalarNode, SequenceNode

    try:
        package = mapping(yaml.compose(data[XIAOMI]))
        if set(package) != {"automation", "shell_command"}:
            raise DeployError("The Xiaomi package must contain automation and shell_command sections.")
        xiaomi_commands = mapping(package["shell_command"])
        if DISPLAY in data:
            display_commands(data[DISPLAY])
            if DISPLAY_COMMANDS.intersection(xiaomi_commands):
                raise DeployError("The Xiaomi and Mac mini display packages define the same shell commands.")
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


def mapping(node):
    from yaml.nodes import MappingNode, ScalarNode

    if not isinstance(node, MappingNode) or not all(isinstance(key, ScalarNode) for key, _ in node.value):
        raise DeployError("Expected a YAML mapping.")
    fields = {key.value: value for key, value in node.value}
    if len(fields) != len(node.value):
        raise DeployError("Duplicate YAML mapping keys.")
    return fields


def display_commands(text):
    import yaml
    from yaml.nodes import ScalarNode

    package = mapping(yaml.compose(text))
    if set(package) != {"shell_command"}:
        raise DeployError("The Mac mini display package must contain only shell_command.")
    commands = mapping(package["shell_command"])
    if set(commands) != DISPLAY_COMMANDS or any(
            not isinstance(command, ScalarNode) or command.tag != "tag:yaml.org,2002:str"
            or not command.value.strip() for command in commands.values()):
        raise DeployError("The Mac mini display package must contain both display commands as strings.")
    return {name: command.value for name, command in commands.items()}


def migrate_display(text, desired):
    """Remove matching legacy definitions while preserving unrelated configuration."""
    import yaml
    from yaml.nodes import MappingNode, ScalarNode

    config = yaml.compose(text)
    shell = mapping(config).get("shell_command")
    if shell is None:
        return text
    if not isinstance(shell, MappingNode):
        raise DeployError("Move the legacy display commands out of the shell_command include before deploying.")
    mapping(shell)
    legacy = [(key, value) for key, value in shell.value if key.value in DISPLAY_COMMANDS]
    if not legacy:
        return text
    if config.flow_style or shell.flow_style:
        raise DeployError("Expected block YAML for the legacy display commands.")

    lines = text.splitlines(keepends=True)
    remove = set()
    for key, value in legacy:
        line = key.start_mark.line
        prefix = " " * key.start_mark.column + key.value + ":"
        if (not isinstance(value, ScalarNode) or value.tag != "tag:yaml.org,2002:str"
                or value.value != desired[key.value] or line != value.start_mark.line
                or line != value.end_mark.line or not lines[line].startswith(prefix)):
            raise DeployError(f"Review the legacy {key.value} in configuration.yaml before deploying.")
        remove.add(line)
    if len(legacy) == len(shell.value):
        key = next(key for key, _ in config.value if key.value == "shell_command")
        line = key.start_mark.line
        if not lines[line].startswith("shell_command:") or line >= min(remove):
            raise DeployError("Expected a standalone shell_command section in configuration.yaml.")
        remove.add(line)
    return "".join(line for index, line in enumerate(lines) if index not in remove)


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


def deployment_changes(data, original):
    updated = dict(data)
    if DISPLAY in data:
        updated[ROOT_CONFIG] = migrate_display(original[ROOT_CONFIG], display_commands(data[DISPLAY]))
    return {name: value for name, value in updated.items() if value != original.get(name)}


def deployment_snapshot(data):
    original = read_managed()
    if DISPLAY in data:
        original[ROOT_CONFIG] = read_file(ROOT_CONFIG)
    return original


def apply(data):
    validate_yaml(data)
    if not deployment_changes(data, deployment_snapshot(data)):
        return {"status": "unchanged"}
    directory = CONFIG / ".automation-deploy-backups"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise DeployError("Expected a private automation backup directory.")
    with (directory / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_layout()
        original = deployment_snapshot(data)
        changed = deployment_changes(data, original)
        if not changed:
            return {"status": "unchanged"}
        backup = Path(tempfile.mkdtemp(prefix="previous-", dir=directory))
        metadata = {}
        for name in changed:
            previous = original.get(name)
            metadata[name] = (CONFIG / (XIAOMI if previous is None else name)).stat()
            if previous is not None:
                path = backup / name
                path.parent.mkdir(exist_ok=True)
                path.write_text(previous)

        domains = []
        if {XIAOMI, DISPLAY, ROOT_CONFIG}.intersection(changed):
            domains.append("shell_command")
        if {AUTOMATIONS, XIAOMI}.intersection(changed):
            domains.append("automation")
        expected = {**original, **changed}
        written = []
        reloading = False
        try:
            for name, value in changed.items():
                if read_file(name) != original.get(name):
                    raise DeployError(f"{name} changed while deployment was in progress.")
                written.append(name)
                replace(CONFIG / name, value, metadata[name])
            check_core()
            if any(read_file(name) != value for name, value in expected.items()):
                raise DeployError("The managed files changed during validation.")
            reloading = True
            for domain in domains:
                reload_domain(domain)
            if any(read_file(name) != value for name, value in expected.items()):
                raise DeployError("The managed files changed during reload.")
        except (OSError, UnicodeError, DeployError) as error:
            rollback_failed = False
            for name in reversed(written):
                path = CONFIG / name
                try:
                    current = read_file(name)
                    previous = original.get(name)
                    if current == changed[name]:
                        if previous is None:
                            path.unlink()
                        else:
                            replace(path, previous, metadata[name])
                    elif current != previous:
                        rollback_failed = True
                except (OSError, UnicodeError, DeployError):
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
    return {"status": "deployed", "changed": list(changed), "backup": str(backup)}


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
