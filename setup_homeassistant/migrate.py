#!/usr/bin/env python3
"""Back up Home Assistant OS over SSH and restore it during onboarding."""

import argparse
import datetime as dt
import getpass
import hashlib
import http.client
import itertools
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlsplit


ARCHIVE = "home-assistant.tar"
KEY_FILE = "restore-key.txt"
CHECKSUM = "sha256.txt"
CHUNK_SIZE = 1024 * 1024
AGENT = "hassio.local"
BACKUP_API = "/api/onboarding/backup"
DEFAULT_OUTPUT = Path.home() / ".local/share/homeassistant-migration"
NETWORK_ERRORS = (OSError, http.client.HTTPException)


class MigrationError(Exception):
    pass


def json_object(raw):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise MigrationError("Expected a JSON response from Home Assistant.") from exc
    if not isinstance(value, dict):
        raise MigrationError("Expected a JSON object from Home Assistant.")
    return value


def log(message):
    print(message, file=sys.stderr, flush=True)


def ssh_curl(source, endpoint, *, body=None, output=None):
    command = ["curl", "-sS", "--header", "@/dev/fd/3"]
    if output is None:
        command += ["--max-time", "30"]
    else:
        command += ["--fail", "--speed-limit", "1", "--speed-time", "60"]
    if body is not None:
        command += ["--header", "Content-Type: application/json", "--data-binary", "@-"]
    command.append(f"http://supervisor{endpoint}")
    # The SSH add-on exports the token in the login profile. FD 3 keeps it
    # out of command arguments and leaves stdin available for the backup key.
    script = (
        'test -n "$SUPERVISOR_TOKEN" || '
        '{ echo "No Supervisor token in the SSH login environment." >&2; exit 1; }; '
        f'exec {shlex.join(command)} 3<<<"Authorization: Bearer $SUPERVISOR_TOKEN"'
    )
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o",
         "StrictHostKeyChecking=yes", "--", source, f"bash -lc {shlex.quote(script)}"],
        input=json.dumps(body).encode() if body is not None else b"",
        stdout=output if output is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        raise ConnectionError(detail[-1] if detail else f"SSH exited {result.returncode}")
    if output is None:
        response = json_object(result.stdout)
        if response.get("result") != "ok" or not isinstance(response.get("data"), dict):
            raise MigrationError(f"Supervisor {endpoint} failed. {response.get('message', '')}")
        return response["data"]


def wait_for_backup(source, job_id, timeout):
    if not isinstance(job_id, str) or not re.fullmatch(r"[\da-f]{32}", job_id):
        raise MigrationError("Supervisor did not return a backup job ID.")
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            job = ssh_curl(source, f"/jobs/{job_id}")
        except ConnectionError as exc:
            # Backing up the SSH add-on can temporarily interrupt access.
            last_error = str(exc)
        else:
            if job.get("done") is True:
                if job.get("errors"):
                    raise MigrationError(f"Supervisor backup job {job_id} failed. Check Supervisor logs.")
                return job.get("reference")
        time.sleep(5)
    raise MigrationError(f"Timed out waiting for backup job {job_id}. {last_error}".rstrip())


def private_text(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_metadata(path):
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            if member.name in {"./backup.json", "backup.json", "./snapshot.json", "snapshot.json"}:
                if not member.isfile() or member.size > CHUNK_SIZE:
                    break
                with archive.extractfile(member) as stream:
                    metadata = json_object(stream.read())
                if metadata.get("homeassistant") and isinstance(metadata.get("slug"), str):
                    return metadata
                break
    raise MigrationError("The archive lacks valid Home Assistant Core backup metadata.")


def create_backup(args):
    installed = ssh_curl(args.source, "/addons")["addons"]
    expected = {app["slug"] for app in installed}
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundle = Path(tempfile.mkdtemp(prefix=f"ha-{timestamp}-", dir=output_dir))
    key = secrets.token_urlsafe(32)
    private_text(bundle / KEY_FILE, key)
    log(f"Creating a full encrypted backup on {args.source}. Recovery key saved in {bundle}")
    started = ssh_curl(args.source, "/backups/new/full", body={
        "name": bundle.name,
        "password": key,
        "location": ".local",
        "homeassistant_exclude_database": False,
        "background": True,
    })
    slug = started.get("slug") or wait_for_backup(args.source, started.get("job_id"), args.timeout)
    if not isinstance(slug, str) or not re.fullmatch(r"[\da-f]{8}", slug):
        raise MigrationError("Supervisor did not report a completed backup ID.")
    info = ssh_curl(args.source, f"/backups/{slug}/info")
    missing = expected - {app["slug"] for app in info.get("addons", [])}
    if missing:
        raise MigrationError(f"Backup {slug} omitted installed add-ons: {', '.join(sorted(missing))}")
    if info.get("type") != "full" or not info.get("protected") or not info.get("homeassistant"):
        raise MigrationError(f"Backup {slug} is missing full encrypted Home Assistant data.")
    log(f"Downloading backup {slug} with {len(expected)} add-ons.")
    with tempfile.NamedTemporaryFile(dir=bundle, prefix="download-", delete=False) as stream:
        partial = Path(stream.name)
        try:
            ssh_curl(args.source, f"/backups/{slug}/download?location=.local", output=stream)
            if partial.stat().st_size != info.get("size_bytes") or backup_metadata(partial)["slug"] != slug:
                raise MigrationError(f"Downloaded archive did not match backup {slug}.")
            private_text(bundle / CHECKSUM, sha256(partial))
            partial.rename(bundle / ARCHIVE)
        finally:
            partial.unlink(missing_ok=True)
    print(bundle / ARCHIVE)


class Target:
    def __init__(self, url):
        address = urlsplit(url)
        if (address.scheme not in {"http", "https"} or not address.hostname or address.username
                or address.path not in {"", "/"} or address.query or address.fragment):
            raise MigrationError("Use the fresh HAOS base URL, for example http://192.168.1.50:8123.")
        self.host = address.hostname
        self.port = address.port
        self.connection = http.client.HTTPSConnection if address.scheme == "https" else http.client.HTTPConnection

    def request(self, method, path, *, body=None, headers=None, timeout=15):
        connection = self.connection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            # No redirects. A backup or key should only go to the selected host.
            return response.status, response.read(4 * CHUNK_SIZE)
        finally:
            connection.close()

    def backup_info(self):
        status, raw = self.request("GET", f"{BACKUP_API}/info")
        if status != 200:
            raise MigrationError(f"Target onboarding backup API returned HTTP {status}.")
        return json_object(raw)

    def upload(self, path, timeout):
        boundary = secrets.token_hex(16)
        start = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{ARCHIVE}"\r\n'
            "Content-Type: application/x-tar\r\n\r\n"
        ).encode()
        end = f"\r\n--{boundary}--\r\n".encode()
        with path.open("rb") as stream:
            chunks = iter(lambda: stream.read(CHUNK_SIZE), b"")
            status, raw = self.request(
                "POST", f"{BACKUP_API}/upload?agent_id={AGENT}",
                body=itertools.chain((start,), chunks, (end,)),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                         "Content-Length": str(len(start) + os.fstat(stream.fileno()).st_size + len(end))},
                timeout=timeout,
            )
        if status not in {200, 201}:
            raise MigrationError(f"Target backup upload returned HTTP {status}.")
        return json_object(raw).get("backup_id")


def wait_for_restore(target, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, raw = target.request("GET", f"{BACKUP_API}/info")
            if status == 200:
                event = json_object(raw).get("last_action_event") or {}
                if event.get("manager_state") == "restore_backup":
                    if event.get("state") == "failed":
                        raise MigrationError(f"Target reported a failed restore ({event.get('reason')}).")
                    if event.get("state") == "completed":
                        return True
            elif status in {401, 404}:
                index_status, _ = target.request("GET", "/")
                api_status, _ = target.request("GET", "/api/")
                if index_status == 200 and api_status == 401:
                    return False  # The restored UI is up, but job details now require login.
        except NETWORK_ERRORS:
            pass
        time.sleep(5)
    raise MigrationError("Could not confirm restore status. Check the target's Supervisor logs before retrying.")


def restore_backup(args):
    path = args.archive.expanduser().resolve()
    metadata = backup_metadata(path)
    checksum = path.with_name(CHECKSUM)
    if path.name == ARCHIVE and checksum.is_file() and sha256(path) != checksum.read_text().strip():
        raise MigrationError("The archive failed its SHA-256 integrity check.")
    target = Target(args.target)
    status, raw = target.request("GET", "/api/onboarding/installation_type")
    if status != 200 or json_object(raw).get("installation_type") != "Home Assistant OS":
        raise MigrationError(f"Target must be Home Assistant OS at the welcome screen (HTTP {status}).")
    info = target.backup_info()
    if info.get("state") != "idle":
        raise MigrationError("The target backup manager is busy. Check the target and retry when it is idle.")
    backup_id = metadata["slug"]
    existing = next((item for item in info["backups"] if item["backup_id"] == backup_id), None)
    if existing is None:
        log(f"Uploading backup {backup_id} to {args.target}.")
        if target.upload(path, args.timeout) != backup_id:
            raise MigrationError("Target returned a different backup ID after upload.")
        info = target.backup_info()
        existing = next((item for item in info["backups"] if item["backup_id"] == backup_id), None)
    agent_info = (existing or {}).get("agents", {}).get(AGENT, {})
    if not agent_info or agent_info.get("size") != path.stat().st_size:
        raise MigrationError("The target's local copy does not match the archive size.")
    payload = {
        "backup_id": backup_id,
        "agent_id": AGENT,
        "restore_addons": [app["slug"] for app in existing["addons"]],
        "restore_folders": existing["folders"],
        "restore_database": existing["database_included"],
    }
    if agent_info.get("protected"):
        adjacent_key = path.with_name(KEY_FILE)
        key_file = args.key_file
        if key_file is None and path.name == ARCHIVE and adjacent_key.is_file():
            key_file = adjacent_key
        key = key_file.expanduser().read_text().strip() if key_file else getpass.getpass("Backup key: ").strip()
        if not key:
            raise MigrationError("This backup needs its encryption key.")
        payload["password"] = key
    log(f"Restoring Home Assistant and {len(payload['restore_addons'])} add-ons. Expect a restart.")
    try:
        status, raw = target.request(
            "POST", f"{BACKUP_API}/restore", body=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, timeout=args.timeout,
        )
    except NETWORK_ERRORS:
        if wait_for_restore(target, args.timeout):
            print(f"Home Assistant confirmed the restore at {args.target}.")
        else:
            print(f"The restored Home Assistant UI is reachable at {args.target}. "
                  "Sign in to confirm the add-ons and repair status.")
        return
    if status != 200:
        if status == 400 and json_object(raw).get("code") == "incorrect_password":
            raise MigrationError("Target rejected the backup key. Check the key and retry.")
        raise MigrationError(f"Target restore returned HTTP {status}. Check the target's Supervisor logs.")
    print(f"Home Assistant confirmed the restore at {args.target}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Create and download a full encrypted backup")
    backup.add_argument("--source", default="ha", help="Source SSH alias (default: ha)")
    backup.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    backup.set_defaults(run=create_backup)
    restore = commands.add_parser("restore", help="Restore all backup contents to a fresh HAOS instance")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--target", required=True, help="Base URL of the fresh HAOS installation")
    restore.add_argument("--key-file", type=Path, help="File containing only the backup encryption key")
    restore.set_defaults(run=restore_backup)
    for command in (backup, restore):
        command.add_argument("--timeout", type=int, default=3600, help="Seconds to wait (default: 3600)")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        args.run(args)
    except (MigrationError, OSError, http.client.HTTPException, tarfile.TarError, KeyError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
