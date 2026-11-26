"""Recover the bundled Jellyfin backend when its macOS launcher outlives it."""

import argparse
import http.client
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time


APP = Path("/Applications/Jellyfin.app")
LABEL = "com.setup-lnx-unx.jellyfin-watchdog"
LAUNCHCTL = "/bin/launchctl"


def healthy():
    connection = http.client.HTTPConnection("127.0.0.1", 8096, timeout=3)
    try:
        connection.request("GET", "/System/Info/Public")
        response = connection.getresponse()
        if response.status != 200:
            return False
        info = json.loads(response.read(8192))
        return isinstance(info, dict) and info.get("ProductName") == "Jellyfin Server"
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()


def launcher_path():
    contents = APP / "Contents"
    with (contents / "Info.plist").open("rb") as plist:
        executable = plistlib.load(plist)["CFBundleExecutable"]
    launcher = contents / "MacOS" / executable
    if not launcher.is_file() or not (contents / "MacOS" / "jellyfin").is_file():
        raise RuntimeError(f"Expected a bundled Jellyfin server in {APP}")
    return str(launcher)


def processes():
    snapshot = subprocess.check_output(
        ["/bin/ps", "-axww", "-o", "pid=,uid=,comm="], text=True, timeout=5
    )
    return [line.split(maxsplit=2) for line in snapshot.splitlines() if line.strip()]


def quit_launcher(pid):
    try:
        os.kill(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(10):
        time.sleep(1)
        if all(entry[0] != pid for entry in processes()):
            return
    raise RuntimeError("The Jellyfin launcher did not exit after SIGTERM")


def recover():
    if healthy():
        return
    time.sleep(2)
    if healthy():
        return

    launcher = launcher_path()
    running = processes()
    if any(Path(command).name == "jellyfin" for _, _, command in running):
        raise RuntimeError("Health check failed while a Jellyfin backend is still running")

    for pid, uid, command in running:
        if uid == str(os.getuid()) and command == launcher:
            print("Stopping stale Jellyfin launcher", flush=True)
            quit_launcher(pid)
            break

    if healthy() or any(Path(command).name == "jellyfin" for _, _, command in processes()):
        return

    print("Starting Jellyfin after its backend exited", flush=True)
    subprocess.run(["/usr/bin/open", "-gj", "-a", str(APP)], check=True, timeout=10)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if healthy():
            print("Jellyfin HTTP service recovered", flush=True)
            return
        time.sleep(1)
    raise RuntimeError("Jellyfin did not become healthy within 30 seconds")


def replace_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        staged = Path(temp.name)
        try:
            temp.write(content)
            temp.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def install():
    launcher_path()
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if subprocess.run([LAUNCHCTL, "print", domain], **quiet).returncode != 0:
        raise RuntimeError("Log into the Mac desktop as the Jellyfin user before installing")

    library = Path.home() / "Library"
    script = library / "Application Support" / "Jellyfin Watchdog" / "watchdog.py"
    plist = library / "LaunchAgents" / f"{LABEL}.plist"
    log = library / "Logs" / "jellyfin-watchdog.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    definition = plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-u", str(script), "--check"],
        "RunAtLoad": True,
        "StartInterval": 60,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    })

    replace_file(script, Path(__file__).read_bytes())
    loaded = subprocess.run([LAUNCHCTL, "print", service], **quiet).returncode == 0
    if not plist.exists() or plist.read_bytes() != definition:
        if loaded:
            subprocess.run([LAUNCHCTL, "bootout", service], check=True)
            loaded = False
        replace_file(plist, definition)
    subprocess.run([LAUNCHCTL, "enable", service], check=True)
    if not loaded:
        subprocess.run([LAUNCHCTL, "bootstrap", domain, str(plist)], check=True)
    print(f"Jellyfin watchdog enabled (every 60 seconds). Recovery log: {log}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run one health check")
    args = parser.parse_args()
    try:
        recover() if args.check else install()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Jellyfin watchdog: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
