#!/usr/bin/env python3
"""Restart a user's Codex processes only when auth.json changes account.

The state file contains only SHA-256(identity), never an identity or credential.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
from typing import Any


EXPLICIT_ID_PATHS = (
    ("tokens", "account_id"),
    ("account_id",),
    ("account", "id"),
)
TOKEN_PATHS = (
    ("tokens", "id_token"),
    ("id_token",),
    ("tokens", "access_token"),
    ("access_token",),
)
JWT_ACCOUNT_CLAIMS = ("account_id", "chatgpt_account_id")


class SafeAuthError(Exception):
    """An auth file condition for which Codex must be left untouched."""


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"{timestamp} {message}", flush=True)


def nested_value(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    encoded = parts[1]
    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    payload = json.loads(decoded)
    if not isinstance(payload, dict):
        raise ValueError("JWT payload is not an object")
    return payload


def stable_identity(document: Any) -> tuple[str, str]:
    if not isinstance(document, dict):
        raise SafeAuthError("auth JSON root is not an object")

    for path in EXPLICIT_ID_PATHS:
        value = nested_value(document, path)
        if isinstance(value, str) and value.strip():
            return "explicit:" + value.strip(), ".".join(path)

    for token_path in TOKEN_PATHS:
        token = nested_value(document, token_path)
        if not isinstance(token, str) or not token:
            continue
        try:
            payload = decode_jwt_payload(token)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue

        namespaces = [payload]
        for value in payload.values():
            if isinstance(value, dict):
                namespaces.append(value)
        for namespace in namespaces:
            for claim in JWT_ACCOUNT_CLAIMS:
                value = namespace.get(claim)
                if isinstance(value, str) and value.strip():
                    return "jwt-account:" + value.strip(), f"{'.'.join(token_path)}:{claim}"
        subject = payload.get("sub")
        if isinstance(subject, str) and subject.strip():
            return "jwt-sub:" + subject.strip(), f"{'.'.join(token_path)}:sub"

    raise SafeAuthError("no stable account identity found")


def read_identity(auth_file: Path, expected_uid: int) -> tuple[str, str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(auth_file, flags)
    except OSError as exc:
        raise SafeAuthError(f"cannot open auth file: {exc.strerror}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise SafeAuthError("auth path is not a regular file")
        if metadata.st_uid != expected_uid:
            raise SafeAuthError("auth file is not owned by the configured user")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            document = json.load(stream)
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise SafeAuthError(f"cannot parse auth file: {type(exc).__name__}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    return stable_identity(document)


def identity_with_retries(auth_file: Path, expected_uid: int, retries: int, delay: float) -> tuple[str, str]:
    last_error: SafeAuthError | None = None
    for attempt in range(retries + 1):
        try:
            return read_identity(auth_file, expected_uid)
        except SafeAuthError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def write_hash_atomic(state_file: Path, digest: str) -> None:
    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_file.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".identity.", dir=state_file.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            descriptor = -1
            stream.write(digest + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, state_file)
        os.chmod(state_file, 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def read_saved_hash(state_file: Path) -> str | None:
    try:
        metadata = state_file.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise SafeAuthError("state file ownership or mode is unsafe")
        value = state_file.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise SafeAuthError(f"cannot read state file: {type(exc).__name__}") from exc
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SafeAuthError("state file is invalid")
    return value


def executable_is_codex(executable: Path, exact_executable: Path, release_root: Path | None) -> bool:
    if executable == exact_executable:
        return True
    if release_root is None:
        return False
    try:
        relative = executable.relative_to(release_root)
    except ValueError:
        return False
    return len(relative.parts) == 3 and relative.parts[1:] == ("bin", "codex")


def codex_pids(uid: int, codex_executable: Path, release_root: Path | None) -> list[int]:
    result: list[int] = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            if proc_dir.stat().st_uid != uid:
                continue
            executable = Path(os.readlink(proc_dir / "exe"))
            if executable_is_codex(executable, codex_executable, release_root):
                result.append(int(proc_dir.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
    return sorted(result)


def terminate_codex(uid: int, codex_executable: Path, release_root: Path | None, dry_run: bool) -> int:
    count = 0
    for pid in codex_pids(uid, codex_executable, release_root):
        try:
            proc_dir = Path("/proc") / str(pid)
            if proc_dir.stat().st_uid != uid:
                continue
            executable = Path(os.readlink(proc_dir / "exe"))
            if not executable_is_codex(executable, codex_executable, release_root):
                continue
            if not dry_run:
                os.kill(pid, signal.SIGTERM)
            count += 1
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-file", required=True, type=Path)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--codex-exe", required=True, type=Path)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--retry-count", type=int, default=4)
    parser.add_argument("--retry-delay", type=float, default=0.25)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.uid != os.getuid():
        log("failure: detector UID differs from configured UID; no processes touched")
        return 2
    state_dir = args.state_file.parent
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = state_dir / ".lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            identity, source = identity_with_retries(
                args.auth_file, args.uid, args.retry_count, args.retry_delay
            )
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            old_digest = read_saved_hash(args.state_file)
        except SafeAuthError as exc:
            log(f"failure: {exc}; no processes touched")
            return 1

        if old_digest is None:
            write_hash_atomic(args.state_file, digest)
            log(f"success: baseline initialized hash={digest[:12]} source={source}")
            return 0
        if old_digest == digest:
            log(f"success: account unchanged hash={digest[:12]}")
            return 0

        if not args.dry_run:
            write_hash_atomic(args.state_file, digest)
        count = terminate_codex(
            args.uid,
            Path(os.path.realpath(args.codex_exe)),
            Path(os.path.realpath(args.release_root)) if args.release_root else None,
            args.dry_run,
        )
        action = "would-send-SIGTERM" if args.dry_run else "sent-SIGTERM"
        log(
            f"success: account changed old={old_digest[:12]} new={digest[:12]} "
            f"{action} count={count}"
        )
        return 0
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
