#!/usr/bin/env python3
"""Credential-free tests for codex_auth_account_monitor.py."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("codex_auth_account_monitor.py")


def jwt(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "fixture." + encoded + ".signature"


def write_auth(path: Path, account: str, generation: int) -> None:
    path.write_text(
        json.dumps(
            {
                "tokens": {
                    "account_id": account,
                    "access_token": jwt({"sub": account, "exp": generation}),
                    "refresh_token": f"sanitized-fixture-{generation}",
                },
                "last_refresh": f"fixture-{generation}",
            }
        )
    )
    path.chmod(0o600)


def invoke(auth: Path, state: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--auth-file", str(auth),
            "--state-file", str(state),
            # In dry-run this deliberately matches the detector's Python
            # executable, proving that the signal branch finds a real PID.
            "--codex-exe", sys.executable,
            "--uid", str(Path(auth).stat().st_uid),
            "--retry-count", "1",
            "--retry-delay", "0",
            "--dry-run",
        ],
        text=True,
        capture_output=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="codex-monitor-test-") as directory:
        root = Path(directory)
        auth, state = root / "auth.json", root / "identity.sha256"

        write_auth(auth, "fixture-account-a", 1)
        baseline = invoke(auth, state)
        assert baseline.returncode == 0 and "baseline initialized" in baseline.stdout

        write_auth(auth, "fixture-account-a", 2)
        same = invoke(auth, state)
        assert same.returncode == 0 and "account unchanged" in same.stdout
        print("PASS same account with refreshed token/expiry: no restart")

        write_auth(auth, "fixture-account-b", 3)
        different = invoke(auth, state)
        assert different.returncode == 0 and "would-send-SIGTERM" in different.stdout
        assert "count=0" not in different.stdout
        print("PASS different account: SIGTERM action would occur (dry-run)")

        auth.write_text('{"tokens":')
        auth.chmod(0o600)
        malformed = invoke(auth, state)
        assert malformed.returncode != 0 and "no processes touched" in malformed.stdout
        print("PASS malformed/partial JSON: safe error, no restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
