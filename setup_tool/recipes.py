"""Plan and run explicit package-owned workflows. Planning never executes code."""
import os
import re
import shlex
import shutil
import subprocess
import sys

from . import configuration, managers
from .catalog import ROOT, SYSTEMS, SetupError, local_path

ACTIONS = ("install", "configure", "run", "remove")


def validate_recipes(item, root):
    recipes = item.get("recipes", {})
    defaults = item.get("defaults", {})
    if not isinstance(recipes, dict) or not isinstance(defaults, dict):
        raise ValueError("recipes and defaults must be objects")
    for name, recipe in recipes.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or not isinstance(recipe, dict):
            raise ValueError("recipe identifiers must be lowercase words separated by hyphens")
        required = {"action", "os", "script", "interpreter", "description", "effects", "requires", "parameters"}
        if not required <= set(recipe) or set(recipe) - required - {"arguments", "bash_min_version"}:
            raise ValueError(f"missing or unknown fields in recipe {name}")
        if recipe["action"] not in ACTIONS or recipe["interpreter"] not in {"bash", "sh", "python3"}:
            raise ValueError(f"invalid action/interpreter for {name}")
        if not isinstance(recipe["os"], list) or not recipe["os"] or any(o not in SYSTEMS for o in recipe["os"]):
            raise ValueError(f"invalid OS list for {name}")
        path = local_path(recipe["script"], root)
        if not path.is_relative_to((root / "packages" / item["name"]).resolve()):
            raise ValueError(f"recipe {name} must belong to its package directory")
        for field in ("description", "effects"):
            if not isinstance(recipe[field], str) or not recipe[field]:
                raise ValueError(f"{name}: {field} must describe the operation")
        if not isinstance(recipe["requires"], list) or any(
            not isinstance(command, str) or not re.fullmatch(r"[a-zA-Z0-9_.+-]+", command)
            for command in recipe["requires"]
        ):
            raise ValueError(f"{name}: requires must list executable names")
        if not isinstance(recipe["parameters"], dict):
            raise ValueError(f"{name}: parameters must be an object")
        for key, param in recipe["parameters"].items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not isinstance(param, dict):
                raise ValueError(f"{name}: invalid parameter")
            if key in {"REPO_ROOT", "PYTHON", "OS"}:
                raise ValueError(f"{name}: parameter {key} is reserved for the runner")
            if set(param) - {"description", "required", "default"} or not isinstance(param.get("description"), str):
                raise ValueError(f"{name}: invalid parameter description")
            if not isinstance(param.get("required", False), bool) or not isinstance(param.get("default", ""), str):
                raise ValueError(f"{name}: invalid parameter default/required flag")
        if "arguments" in recipe:
            args = recipe["arguments"]
            if (not isinstance(args, dict) or set(args) != {"minimum", "usage"}
                    or not isinstance(args["minimum"], int) or args["minimum"] < 0
                    or not isinstance(args["usage"], str)):
                raise ValueError(f"{name}: arguments requires minimum and usage")
        if "bash_min_version" in recipe and (recipe["interpreter"] != "bash" or recipe["bash_min_version"] not in (3, 4, 5)):
            raise ValueError(f"{name}: invalid Bash version")
    for action, targets in defaults.items():
        if action not in {"install", "configure"} or not isinstance(targets, dict):
            raise ValueError("defaults can only select install/configure recipes")
        for target, name in targets.items():
            if name not in recipes or recipes[name]["action"] != action or target not in recipes[name]["os"]:
                raise ValueError(f"invalid {action} default for {target}")


def select(item, action, target, choice=None, optional=False):
    available = {name: r for name, r in item.get("recipes", {}).items()
                 if r["action"] == action and target in r["os"]}
    if choice:
        if choice not in available:
            raise SetupError(f"No {action} recipe '{choice}' for {item['name']} on {target}. "
                             f"Choices: {', '.join(available) or 'none'}")
        return ("script", available[choice], choice)
    # Existing narrow, managed methods always take priority over migrated alternatives.
    if action in {"install", "configure"} and target in item.get(action, {}):
        return ("manager" if action == "install" else "builtin", item[action][target], action)
    default = item.get("defaults", {}).get(action, {}).get(target)
    if default:
        return ("script", available[default], default)
    if available:
        raise SetupError(f"Choose a {action} recipe for {item['name']}: "
                         + ", ".join(available) + ". Use --recipe NAME (or --" + action + "-recipe with setup).")
    if optional:
        return None
    raise SetupError(f"No managed {action} recipe for {item['name']} on {target}. Use ./setup show {item['name']} --os {target}.")


def script_command(recipe, arguments):
    interpreter = recipe["interpreter"]
    if interpreter == "python3":
        prefix = [sys.executable]
    elif interpreter == "bash":
        prefix = ["bash", "-e", "-o", "pipefail"]
    else:
        prefix = ["sh", "-e"]
    return [*prefix, str(local_path(recipe["script"])), *arguments]


def describe(operation, arguments, parameters):
    kind, recipe, name = operation
    if kind == "manager":
        print("  " + shlex.join(managers.command(recipe)))
        print("  The package manager may install required dependencies.")
    elif kind == "builtin":
        for line in configuration.describe(recipe):
            print("  " + line)
    else:
        print(f"  Recipe: {name}\n  {recipe['effects']}")
        print("  " + shlex.join(script_command(recipe, arguments)))
        print("  Working directory: " + str(local_path(recipe["script"]).parent))
        if recipe.get("arguments"):
            print("  Script arguments: " + recipe["arguments"]["usage"])
        for key, param in recipe["parameters"].items():
            value = parameters.get(key, param.get("default", "<required>" if param.get("required") else "<unset>"))
            print(f"  {key}={value} — {param['description']}")


def preflight(operation, arguments, parameters, check_commands=True):
    """Validate inputs before any writes; probe commands again before execution."""
    kind, recipe, name = operation
    if kind == "manager":
        managers.require(recipe["manager"])
        return
    if kind == "builtin":
        return
    for key, param in recipe["parameters"].items():
        if param.get("required") and not parameters.get(key, param.get("default")):
            raise SetupError(f"Recipe {name} requires --set {key}=VALUE: {param['description']}")
    spec = recipe.get("arguments", {})
    if len(arguments) < spec.get("minimum", 0):
        raise SetupError(f"Recipe {name} requires arguments after --: {spec['usage']}")
    if not check_commands:
        return
    for executable in [script_command(recipe, arguments)[0], *recipe["requires"]]:
        if not shutil.which(executable):
            raise SetupError(f"Recipe {name} requires '{executable}'; it will not be installed automatically.")
    if recipe.get("bash_min_version"):
        result = managers.capture(["bash", "-c", 'printf "%s" "${BASH_VERSINFO[0]}"'])
        if result.returncode or not result.stdout.isdigit() or int(result.stdout) < recipe["bash_min_version"]:
            raise SetupError(f"Recipe {name} requires Bash {recipe['bash_min_version']}+ on PATH.")


def execute(operation, arguments, parameters, target):
    kind, recipe, name = operation
    if kind == "manager":
        managers.install(recipe)
    elif kind == "builtin":
        configuration.configure(recipe)
    else:
        environment = os.environ.copy()
        # Only declared, namespaced parameters enter the script environment.
        for key, param in recipe["parameters"].items():
            environment.pop("SETUP_" + key, None)
            if key in parameters or "default" in param:
                environment["SETUP_" + key] = parameters.get(key, param.get("default", ""))
        environment.update(SETUP_REPO_ROOT=str(ROOT), SETUP_PYTHON=sys.executable, SETUP_OS=target)
        result = subprocess.run(script_command(recipe, arguments), cwd=local_path(recipe["script"]).parent,
                                env=environment, check=False)
        if result.returncode:
            raise SetupError(f"Recipe {name} failed with exit code {result.returncode}; later phases were not run.")
