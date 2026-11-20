#!/usr/bin/env python3
"""Install the official Linux desktop app replacing the existing user installation."""
import os
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request

VERSION = '2.33.0-4731201358004224'
BASE = 'https://storage.googleapis.com/antigravity-public/antigravity-hub'


def discover_app(extracted):
    """Find a uniquely named executable without assuming archive nesting or case."""
    candidates = sorted(
        path for path in extracted.rglob('*')
        if path.name.casefold() == 'antigravity'
        and not path.is_symlink() and path.is_file() and os.access(path, os.X_OK)
    )
    if len(candidates) != 1:
        found = ', '.join(str(path.relative_to(extracted)) for path in candidates) or 'none'
        raise SystemExit(f'Expected one executable Antigravity app; found: {found}')
    # Strip only redundant enclosing directories. Keep all companion files,
    # including resources outside the executable's own directory.
    root = extracted
    while True:
        entries = list(root.iterdir())
        if len(entries) != 1 or entries[0].is_symlink() or not entries[0].is_dir():
            break
        root = entries[0]
    return root, candidates[0].relative_to(root)


def install():
    if platform.system() != 'Linux':
        raise SystemExit('This installer supports Linux only')
    architecture = {'x86_64': 'linux-x64', 'aarch64': 'linux-arm'}.get(platform.machine())
    if not architecture:
        raise SystemExit('Supported architectures: x86_64 and aarch64')
    if not hasattr(tarfile, 'data_filter'):
        raise SystemExit('Use Python 3.12+ (or a Python with tarfile.data_filter) for safe archive extraction')
    home = Path.home()
    destination = home / '.local/share/antigravity'
    launcher = home / 'bin/antigravity'
    desktop = home / '.local/share/applications/antigravity.desktop'
    if launcher.exists() and not launcher.is_symlink():
        raise SystemExit(f'Refusing to replace existing file: {launcher}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staging = Path(temporary)
        archive = staging / 'app.tar.gz'
        url = f'{BASE}/{VERSION}/{architecture}/Antigravity.tar.gz'
        print(f'Downloading {url}', flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        extracted = staging / 'unpacked'
        extracted.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(extracted, filter='data')
        app_root, executable = discover_app(extracted)
        previous = staging / 'previous'
        if destination.is_symlink():
            raise SystemExit(f'Refusing to replace a symlinked install directory: {destination}')
        if destination.exists():
            destination.rename(previous)
        try:
            app_root.rename(destination)
        except BaseException:
            if previous.exists():
                previous.rename(destination)
            raise
        # TemporaryDirectory removes the replaced installation after success.
    binary = destination / executable
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SystemExit(f'Incomplete installation: {binary}')
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if launcher.is_symlink():
        launcher.unlink()
    launcher.symlink_to(binary)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    # Desktop-entry Exec escaping differs from shell quoting.
    escaped = str(binary).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    if '\n' in escaped or '\r' in escaped:
        raise SystemExit('Unsupported newline in installation path')
    desktop.write_text('[Desktop Entry]\nType=Application\nName=Antigravity App\n'
                       f'Exec="{escaped}"\nTerminal=false\nCategories=Development;\n')
    print(f'Installed {VERSION}: {binary}\nLaunch with: {launcher}')


if __name__ == '__main__':
    install()
