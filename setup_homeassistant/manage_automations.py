#!/usr/bin/env python3
"""Version the Home Assistant automation YAML with age and deploy it over SSH."""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from automation_remote import MANAGED, decode_bundle

HERE = Path(__file__).resolve().parent
PRIVATE = HERE / "automations"
BUNDLE = PRIVATE / "automation-config.age"
RECIPIENTS = PRIVATE / "recipients.txt"
WORKTREE = PRIVATE / "worktree"
BASELINE = WORKTREE / ".baseline"
IDENTITY = Path.home() / ".local/share/homeassistant-automations/identity.txt"


class AutomationError(Exception):
    pass


def encode(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")


def fingerprint(data):
    return hashlib.sha256(encode(data)).hexdigest()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise AutomationError(f"Refusing to write through a symlink at {path}.")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def age(args, data=None):
    try:
        result = subprocess.run(["age", *args], input=data, stdout=subprocess.PIPE, check=True)
    except FileNotFoundError:
        raise AutomationError("Install age to read or write the encrypted automation bundle.") from None
    except subprocess.CalledProcessError:
        raise AutomationError("age could not read or write the automation bundle.") from None
    return result.stdout


def canonical(identity):
    if not identity.is_file():
        raise AutomationError(f"An age identity is required at {identity} or via --identity.")
    if not BUNDLE.is_file():
        raise AutomationError("No checked-in automation bundle. Run capture to import it from Home Assistant.")
    return decode_bundle(age(["--decrypt", "--identity", str(identity), str(BUNDLE)]))


def seal_bundle(data, identity):
    raw = encode(data)
    encrypted = age(["--encrypt", "--armor", "--recipients-file", str(RECIPIENTS)], raw)
    if age(["--decrypt", "--identity", str(identity)], encrypted) != raw:
        raise AutomationError("Could not verify the encrypted bundle with the selected identity.")
    atomic_write(BUNDLE, encrypted)


def local_files(*, partial=False):
    if WORKTREE.is_symlink() or (WORKTREE / "packages").is_symlink() or BASELINE.is_symlink():
        raise AutomationError("The private working copy must use regular files and directories.")
    if not WORKTREE.exists():
        return None
    files = {}
    for name in MANAGED:
        path = WORKTREE / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise AutomationError("Expected regular YAML files in the private working copy.")
        if path.is_file():
            files[name] = path.read_bytes().decode("utf-8")
    if files and len(files) != len(MANAGED) and not partial:
        raise AutomationError("The private working copy is incomplete. Inspect it before running checkout.")
    return files or None


def checkout(data, *, replace=False):
    existing = local_files(partial=True) or {}
    if not replace and any(text != data[name] for name, text in existing.items()):
        raise AutomationError("Working YAML differs from the encrypted bundle. Seal it or use checkout --replace.")
    for name in MANAGED:
        atomic_write(WORKTREE / name, data[name].encode("utf-8"))
    atomic_write(BASELINE, (fingerprint(data) + "\n").encode())
    print(f"Editable YAML in {WORKTREE}")


def remote(host, operation, data=None):
    worker = (HERE / "automation_remote.py").read_text()
    privileged = shlex.join(["sudo", "-n", "--preserve-env=SUPERVISOR_TOKEN", "python3", "-c", worker, operation])
    command = shlex.join(["bash", "-lc", f"exec {privileged}"])
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o",
         "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "--", host, command],
        input=encode(data) if data is not None else b"",
        stdout=subprocess.PIPE,
    )
    if result.returncode:
        raise AutomationError(f"Home Assistant {operation} over SSH failed on {host}.")
    return decode_bundle(result.stdout) if operation == "snapshot" else json.loads(result.stdout)


def capture(host, identity, replace):
    if BUNDLE.exists():
        if not replace:
            raise AutomationError("A backup already exists. Use capture --replace to adopt the live files.")
        existing = local_files()
        if existing is not None and existing != canonical(identity):
            raise AutomationError("Seal or set aside working edits before importing the live files.")
    elif local_files() is not None:
        raise AutomationError("Set aside the private working copy before importing the live files.")
    data = remote(host, "snapshot")
    seal_bundle(data, identity)
    checkout(data, replace=True)
    print(f"Saved encrypted backup from {host} in {BUNDLE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["capture", "checkout", "diff", "seal", "status", "check", "deploy"])
    parser.add_argument("--host", default="ha", help="Home Assistant SSH alias (default ha)")
    parser.add_argument("--identity", type=Path, default=IDENTITY, help="local age identity file")
    parser.add_argument("--replace", action="store_true", help="replace existing YAML on checkout or capture")
    args = parser.parse_args()
    os.umask(0o077)
    if args.replace and args.command not in ("checkout", "capture"):
        parser.error("--replace applies to checkout and capture")
    if args.command == "capture":
        capture(args.host, args.identity, args.replace)
        return
    if args.command == "check":
        remote(args.host, "check")
        print(f"Home Assistant Core validated the on-disk configuration on {args.host}.")
        return

    saved = canonical(args.identity)
    if args.command == "checkout":
        checkout(saved, replace=args.replace)
        return
    working = local_files()
    if args.command == "diff":
        if working is None:
            raise AutomationError("Run checkout before reviewing local YAML edits.")
        for name in MANAGED:
            sys.stdout.writelines(difflib.unified_diff(
                saved[name].splitlines(keepends=True), working[name].splitlines(keepends=True),
                fromfile=f"saved/{name}", tofile=f"working/{name}",
            ))
    elif args.command == "seal":
        if working is None:
            raise AutomationError("Run checkout before editing and sealing the YAML.")
        if working == saved:
            print("The encrypted bundle already matches the working YAML.")
        else:
            if not BASELINE.is_file() or BASELINE.read_text().strip() != fingerprint(saved):
                raise AutomationError("The encrypted bundle changed since checkout. Set aside and reapply your edits.")
            seal_bundle(working, args.identity)
            atomic_write(BASELINE, (fingerprint(working) + "\n").encode())
            print(f"Sealed working edits in {BUNDLE}")
    elif args.command == "status":
        live = remote(args.host, "snapshot")
        for name in MANAGED:
            state = "matches" if saved[name] == live[name] else "differs from"
            print(f"{name} {state} {args.host}.")
        print("Working YAML has unsealed changes." if working is not None and working != saved
              else "No unsealed working changes.")
    else:
        if working is not None and working != saved:
            raise AutomationError("Working YAML differs from the encrypted bundle. Seal your edits before deploying.")
        result = remote(args.host, "deploy", saved)
        if result.get("status") == "unchanged":
            print(f"{args.host} already matches the encrypted bundle. No reload needed.")
        elif result.get("status") == "deployed":
            print(f"Deployed to {args.host} and reloaded Home Assistant. Backup at {result['backup']}.")
        else:
            raise AutomationError("Unexpected response from Home Assistant deployment.")


if __name__ == "__main__":
    try:
        main()
    except (AutomationError, OSError, ValueError) as error:
        message = str(error) if isinstance(error, AutomationError) else "Could not process the automation files."
        sys.exit(message)
