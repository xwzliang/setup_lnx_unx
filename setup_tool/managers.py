"""Single-package manager adapters; subprocesses always use argv, never a shell."""
import json
import os
import re
import shutil
import subprocess
import sys

from .catalog import SetupError


def command(method):
    manager, package = method["manager"], method["package"]
    options = method.get("options", [])
    return {
        "apt": ["sudo", "apt-get", "install", "-y", package],
        "brew": ["brew", "install", *options, package],
        "pip": [sys.executable, "-m", "pip", "install", package],
        "npm": ["npm", "install", "--global", package],
        "go": ["go", "install", package],
        "snap": ["sudo", "snap", "install", *options, package],
    }[manager]


def capture(argv):
    try:
        return subprocess.run(argv, text=True, capture_output=True, check=False)
    except OSError as exc:
        raise SetupError(f"Could not run {argv[0]}: {exc}") from exc


def require(manager):
    executable = {"apt": "apt-get", "pip": sys.executable}.get(manager, manager)
    if not shutil.which(executable):
        raise SetupError(f"Required tool '{executable}' is missing. Install it separately; no automatic bootstrap.")
    if manager in {"apt", "snap"} and not shutil.which("sudo"):
        raise SetupError("sudo is required for this installation method")
    if manager == "pip":
        if sys.prefix == sys.base_prefix:
            raise SetupError("Python packages require an active virtual environment. Activate one and rerun ./setup.")
        if capture([sys.executable, "-m", "pip", "--version"]).returncode:
            raise SetupError("pip is missing from the active Python environment")


def installed(method):
    manager, package = method["manager"], method["package"]
    if manager == "apt":
        result = capture(["dpkg-query", "-W", "-f=${Status}", package])
        return result.returncode == 0 and result.stdout.strip() == "install ok installed"
    if manager == "brew":
        kind = "--cask" if "--cask" in method.get("options", []) else "--formula"
        result = capture(["brew", "list", kind, "--versions", package])
        return result.returncode == 0 and bool(result.stdout.strip())
    if manager == "snap":
        result = capture(["snap", "list", package])
        return result.returncode == 0 and any(
            line.split()[0] == package for line in result.stdout.splitlines()[1:] if line.split())
    if manager == "npm":
        result = capture(["npm", "list", "--global", "--depth=0", "--json", package])
        try:
            return result.returncode == 0 and package in json.loads(result.stdout).get("dependencies", {})
        except (ValueError, AttributeError):
            raise SetupError("npm returned an invalid installed-package listing")
    if manager == "pip":
        # pip resolves extras and version requirements even if the base distribution exists.
        if re.search(r"[\[=<>]", package):
            return False
        result = capture([sys.executable, "-m", "pip", "show", package])
        return result.returncode == 0
    # go install is the resolver for @version/@latest. Never infer installation
    # from an unrelated executable with the same basename on PATH.
    return False


def install(method):
    require(method["manager"])
    if installed(method):
        print(f"Already installed: {method['package']} ({method['manager']}); skipped.")
        return
    environment = os.environ.copy()
    if method["manager"] == "brew":
        environment["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    result = subprocess.run(command(method), env=environment, check=False)
    if result.returncode:
        raise SetupError(f"{method['manager']} failed with exit code {result.returncode}")
