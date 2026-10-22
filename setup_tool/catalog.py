"""Load and validate the declarative catalog. Never execute catalog contents."""
import json
import platform
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEMS = ("ubuntu", "debian", "macos")
MANAGERS = {"apt", "brew", "pip", "npm", "go", "snap"}
OPTIONS = {"apt": set(), "brew": {"--cask"}, "pip": set(),
           "npm": set(), "go": set(), "snap": {"--classic", "--edge"}}


class SetupError(Exception):
    """An actionable catalog, planning, or execution error."""


def local_path(relative, root=ROOT):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise SetupError(f"Missing or out-of-repository file: {relative}")
    return path


def detect_os():
    if platform.system() == "Darwin":
        return "macos"
    if platform.system() == "Linux":
        try:
            values = dict(line.split("=", 1) for line in
                          Path("/etc/os-release").read_text().splitlines() if "=" in line)
        except OSError:
            return "unknown"
        return values.get("ID", "unknown").strip('"\'')
    return "unknown"


def load_catalog(root=ROOT):
    packages = {}
    names = {}
    for path in sorted((root / "packages").glob("*.json")):
        try:
            item = json.loads(path.read_text())
            if not isinstance(item, dict):
                raise ValueError("manifest must be an object")
            unknown = set(item) - {"name", "description", "aliases", "install", "configure", "references", "notes"}
            if unknown:
                raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
            name = item["name"]
            if name != path.stem or not re.fullmatch(r"[a-z0-9][a-z0-9@._+-]*", name):
                raise ValueError("name must match filename and be a simple lowercase identifier")
            if not isinstance(item["description"], str) or not item["description"]:
                raise ValueError("description is required")
            for key in ("aliases", "notes"):
                if not isinstance(item.get(key, []), list) or any(
                    not isinstance(value, str) or not value for value in item.get(key, [])
                ):
                    raise ValueError(f"{key} must be a list of nonempty strings")
            for key in ("install", "configure"):
                if not isinstance(item.get(key, {}), dict):
                    raise ValueError(f"{key} must be an object")
            if not isinstance(item.get("references", []), list):
                raise ValueError("references must be a list")
            for alias in [name] + item.get("aliases", []):
                if not isinstance(alias, str) or alias in names:
                    raise ValueError(f"invalid or duplicate name/alias: {alias}")
                names[alias] = name
            for os_name, method in item.get("install", {}).items():
                if not isinstance(method, dict) or set(method) - {"manager", "package", "options"}:
                    raise ValueError("install method must contain manager, package, and optional options only")
                manager = method["manager"]
                if os_name not in SYSTEMS or manager not in MANAGERS:
                    raise ValueError("unknown OS or manager")
                if manager in {"apt", "snap"} and os_name == "macos":
                    raise ValueError("Linux manager used for macOS")
                package = method["package"]
                if not isinstance(package, str) or not re.fullmatch(r"[A-Za-z0-9@][A-Za-z0-9@/._+\[\],=-]*", package):
                    raise ValueError("invalid package identifier")
                options = method.get("options", [])
                if not isinstance(options, list) or any(o not in OPTIONS[manager] for o in options):
                    raise ValueError("unsupported manager options")
            for ref in item.get("references", []):
                if not isinstance(ref, dict) or set(ref) != {"path", "os", "note"}:
                    raise ValueError("reference must contain path, os, and note")
                local_path(ref["path"], root)
                if (not isinstance(ref["note"], str) or not ref["note"]
                        or not isinstance(ref["os"], list) or not ref["os"]
                        or any(os_name not in (*SYSTEMS, "openwrt", "all") for os_name in ref["os"])):
                    raise ValueError("references require an OS list and a note")
            for os_name, config in item.get("configure", {}).items():
                if os_name not in SYSTEMS or config not in {"git-aliases", "vim-filetypes", "tmux-plugins"}:
                    raise ValueError("unknown configuration recipe")
            if not any(item.get(key) for key in ("install", "configure", "references")):
                raise ValueError("at least one install method, configuration, or reference is required")
            packages[name] = item
        except (KeyError, TypeError, ValueError, SetupError) as exc:
            raise SetupError(f"{path.relative_to(root)}: {exc}") from exc
    if not packages:
        raise SetupError("No package manifests found")
    return packages


def resolve(packages, name):
    for item in packages.values():
        if name == item["name"] or name in item.get("aliases", []):
            return item
    raise SetupError(f"Unknown package '{name}'. Try: ./setup search {name}")


def supports(item, os_name):
    return (os_name in item.get("install", {}) or os_name in item.get("configure", {})
            or any(os_name in ref["os"] or "all" in ref["os"]
                   for ref in item.get("references", [])))
