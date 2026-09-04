#!/usr/bin/env python3

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


REPO = "jlcodes99/cockpit-tools"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def fail(message):
    print(f"\nERROR: {message}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kwargs):
    print("+", " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True, **kwargs)


def get_release():
    print(f"Checking latest Cockpit Tools release from GitHub...")

    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "cockpit-tools-installer",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except Exception as exc:
        fail(f"Could not query GitHub releases: {exc}")


def normalize_arch():
    machine = platform.machine().lower()

    if machine in ("arm64", "aarch64"):
        return "arm64"

    if machine in ("x86_64", "amd64"):
        return "x64"

    fail(f"Unsupported CPU architecture: {machine}")


def score_asset(asset_name, system, arch):
    """
    Return a score for an asset.
    Higher = better match.
    Negative = reject.
    """
    name = asset_name.lower()

    # Ignore signatures/checksums/updaters.
    if name.endswith((".sig", ".sha256", ".sha512")):
        return -1

    if system == "darwin":
        if not name.endswith(".dmg"):
            return -1

        score = 100

        if arch == "arm64":
            if any(x in name for x in ("aarch64", "arm64")):
                score += 50
            elif any(x in name for x in ("x86_64", "amd64", "x64")):
                return -1

        elif arch == "x64":
            if any(x in name for x in ("x86_64", "amd64", "x64")):
                score += 50
            elif any(x in name for x in ("aarch64", "arm64")):
                return -1

        return score

    if system == "windows":
        # MSI preferred over EXE.
        if name.endswith(".msi"):
            score = 200
        elif name.endswith(".exe"):
            score = 100
        else:
            return -1

        if arch == "arm64":
            if any(x in name for x in ("aarch64", "arm64")):
                score += 50
            elif any(x in name for x in ("x86_64", "amd64", "x64")):
                return -1

        elif arch == "x64":
            if any(x in name for x in ("x86_64", "amd64", "x64")):
                score += 50
            elif any(x in name for x in ("aarch64", "arm64")):
                return -1

        return score

    if system == "linux":
        # User specifically requested Debian/Ubuntu .deb.
        if not name.endswith(".deb"):
            return -1

        score = 100

        if arch == "arm64":
            if any(x in name for x in ("aarch64", "arm64")):
                score += 50
            elif any(x in name for x in ("amd64", "x86_64", "x64")):
                return -1

        elif arch == "x64":
            if any(x in name for x in ("amd64", "x86_64", "x64")):
                score += 50
            elif any(x in name for x in ("aarch64", "arm64")):
                return -1

        return score

    return -1


def choose_asset(release):
    system = platform.system().lower()
    arch = normalize_arch()

    if system not in ("darwin", "windows", "linux"):
        fail(f"Unsupported operating system: {system}")

    print(f"Detected platform: {system}")
    print(f"Detected architecture: {arch}")

    candidates = []

    for asset in release.get("assets", []):
        name = asset.get("name", "")
        score = score_asset(name, system, arch)

        if score >= 0:
            candidates.append((score, asset))

    if not candidates:
        print("\nAvailable release assets:")
        for asset in release.get("assets", []):
            print(f"  - {asset.get('name')}")

        fail(
            f"No compatible installer found for "
            f"{system}/{arch} in release {release.get('tag_name')}"
        )

    candidates.sort(key=lambda x: x[0], reverse=True)

    return candidates[0][1]


def download_asset(asset, directory):
    name = asset["name"]
    url = asset["browser_download_url"]

    destination = directory / name

    print(f"\nDownloading:")
    print(f"  {name}")
    print(f"  {url}")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "cockpit-tools-installer",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            total = response.headers.get("Content-Length")

            with open(destination, "wb") as f:
                downloaded = 0

                while True:
                    chunk = response.read(1024 * 1024)

                    if not chunk:
                        break

                    f.write(chunk)
                    downloaded += len(chunk)

                    if total:
                        percent = downloaded * 100 / int(total)
                        print(
                            f"\rDownloading: {percent:5.1f}%",
                            end="",
                            flush=True,
                        )

        print()

    except Exception as exc:
        fail(f"Download failed: {exc}")

    return destination


def install_macos(dmg):
    print("\nInstalling Cockpit Tools on macOS...")

    mount_dir = Path(tempfile.mkdtemp(prefix="cockpit-tools-mount-"))

    try:
        run([
            "hdiutil",
            "attach",
            str(dmg),
            "-mountpoint",
            str(mount_dir),
            "-nobrowse",
        ])

        apps = list(mount_dir.glob("*.app"))

        if not apps:
            fail("Could not find an .app inside the DMG.")

        app = apps[0]
        destination = Path("/Applications") / app.name

        print(f"Installing {app.name} -> {destination}")

        if destination.exists():
            print("Removing existing Cockpit Tools installation...")
            run(["sudo", "rm", "-rf", str(destination)])

        run([
            "sudo",
            "cp",
            "-R",
            str(app),
            str(destination),
        ])

        # The project's README notes that its current open-source build may
        # trigger Gatekeeper because it is not Apple Developer ID notarized.
        # Remove quarantine on the newly installed application.
        print("Removing macOS quarantine attribute...")
        subprocess.run([
            "sudo",
            "xattr",
            "-rd",
            "com.apple.quarantine",
            str(destination),
        ])

        print("\nCockpit Tools installed successfully.")
        print(f"Application: {destination}")

    finally:
        subprocess.run([
            "hdiutil",
            "detach",
            str(mount_dir),
        ])

        shutil.rmtree(mount_dir, ignore_errors=True)


def install_windows(installer):
    print("\nInstalling Cockpit Tools on Windows...")

    suffix = installer.suffix.lower()

    if suffix == ".msi":
        run([
            "msiexec.exe",
            "/i",
            str(installer),
        ])

    elif suffix == ".exe":
        # Fallback if a release doesn't contain an MSI.
        run([str(installer)])

    else:
        fail(f"Unknown Windows installer type: {suffix}")

    print("\nCockpit Tools installer completed.")


def install_linux(deb):
    print("\nInstalling Cockpit Tools on Debian/Ubuntu...")

    if os.geteuid() == 0:
        run([
            "apt-get",
            "install",
            "-y",
            str(deb),
        ])
    else:
        run([
            "sudo",
            "apt-get",
            "install",
            "-y",
            str(deb),
        ])

    print("\nCockpit Tools installed successfully.")


def main():
    print("=" * 60)
    print(" Cockpit Tools - Latest Release Installer")
    print("=" * 60)

    release = get_release()

    version = release.get("tag_name", "unknown")

    print(f"Latest release: {version}")

    asset = choose_asset(release)

    print(f"Selected package: {asset['name']}")

    with tempfile.TemporaryDirectory(
        prefix="cockpit-tools-installer-"
    ) as tmp:
        tmpdir = Path(tmp)

        installer = download_asset(asset, tmpdir)

        system = platform.system().lower()

        if system == "darwin":
            install_macos(installer)

        elif system == "windows":
            install_windows(installer)

        elif system == "linux":
            install_linux(installer)

    print("\nDone.")


if __name__ == "__main__":
    main()
