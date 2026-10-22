"""User interface: discovery is read-only, and execution is explicitly requested."""
import argparse
import json
import shlex
import subprocess
import sys

from . import configuration, managers, recipes
from .catalog import ROOT, SYSTEMS, SetupError, detect_os, load_catalog, resolve, supports


def parser():
    app = argparse.ArgumentParser(
        description="Find one package, choose an OS, preview its installation and configuration.")
    commands = app.add_subparsers(dest="action", required=True)
    for name in ("list", "search", "show", "install", "configure", "setup", "run", "remove"):
        sub = commands.add_parser(name, help={
            "list": "list packages and available methods",
            "search": "search names, descriptions, aliases, and legacy paths",
            "show": "show installation commands and setup references",
            "install": "preview installation of exactly one package",
            "configure": "preview a configuration recipe for one package",
            "setup": "install and configure one package in order",
            "run": "preview an explicitly selected workflow",
            "remove": "preview an explicitly selected removal recipe",
        }[name])
        if name == "search":
            sub.add_argument("query")
        elif name not in {"list"}:
            sub.add_argument("package")
        sub.add_argument("--os", choices=(*SYSTEMS, "all"),
                         default=None, help="default: host OS for actions, all OSes for discovery")
        if name in {"list", "search", "show"}:
            sub.add_argument("--json", action="store_true", help="machine-readable catalog output")
        if name == "show":
            sub.add_argument("--recipe", help="inspect one named recipe")
            sub.add_argument("--source", action="store_true", help="print selected recipe source (requires --recipe)")
        if name in {*recipes.ACTIONS, "setup"}:
            if name == "setup":
                sub.add_argument("--install-recipe")
                sub.add_argument("--configure-recipe")
                sub.add_argument("--install-arg", action="append", default=[])
                sub.add_argument("--configure-arg", action="append", default=[])
            else:
                sub.add_argument("--recipe", help="choose an alternative script recipe")
            sub.add_argument("--set", dest="parameters", action="append", default=[], metavar="NAME=VALUE",
                             help="set a declared recipe parameter; repeat as needed")
            group = sub.add_mutually_exclusive_group()
            group.add_argument("--apply", action="store_true", help="execute the displayed operation on this host")
            group.add_argument("--dry-run", action="store_true", help="preview only (the default)")
    commands.add_parser("validate", help="validate every manifest and referenced file offline")
    docs = commands.add_parser("docs", help="generate the Markdown package index on stdout")
    docs.add_argument("--check", action="store_true", help="verify docs/packages.md matches the catalog")
    return app


def selected_references(item, target):
    return [ref for ref in item.get("references", [])
            if target == "all" or target in ref["os"] or "all" in ref["os"]]


def show(item, target):
    print(f"{item['name']} — {item['description']}")
    if item.get("aliases"):
        print("Aliases: " + ", ".join(item["aliases"]))
    for note in item.get("notes", []):
        print(f"Note: {note}")
    for os_name, method in item.get("install", {}).items():
        if target not in {"all", os_name}:
            continue
        print(f"\nInstall [{os_name}, {method['manager']}]: {shlex.join(managers.command(method))}")
        print(f"  ./setup install {item['name']} --os {os_name} --apply")
    for os_name, recipe in item.get("configure", {}).items():
        if target not in {"all", os_name}:
            continue
        print(f"\nConfigure [{os_name}]: ./setup configure {item['name']} --os {os_name} --apply")
        for line in configuration.describe(recipe):
            print(f"  {line}")
    for name, recipe in item.get("recipes", {}).items():
        if target != "all" and target not in recipe["os"]:
            continue
        print(f"\nRecipe [{', '.join(recipe['os'])}]: {name}")
        print(f"  ./setup {recipe['action']} {item['name']} --recipe {name}")
        print(f"  {recipe['effects']}\n  Source: {recipe['script']}")
        for key, param in recipe["parameters"].items():
            print(f"  --set {key}=VALUE: {param['description']}" + (" (required)" if param.get("required") else ""))
        if recipe.get("arguments"):
            print("  Arguments after --: " + recipe["arguments"]["usage"])
    refs = selected_references(item, target)
    if refs:
        print("\nRelated sources (select a named recipe above to execute scripts):")
        for ref in refs:
            print(f"  {ref['path']} [{', '.join(ref['os'])}]\n    {ref['note']}")
    if not item.get("install") and not item.get("configure") and not item.get("recipes"):
        print("\nReference only: no managed install/configure recipe yet.")


def index(packages):
    lines = ["# Package index", "", "Generated by `./setup docs`; edit `packages/*/package.json`, then regenerate.",
             "", "Search with `./setup search TERM --os ubuntu` or inspect `./setup show NAME --os macos`.",
             "Use `./setup setup NAME` to preview installation and configuration together. Named scripts appear in `show`.",
             "Package availability depends on the OS release and configured repositories.", "",
             "| Package | Install methods | Configuration | Description |", "| --- | --- | --- | --- |"]
    for item in packages.values():
        methods = ", ".join(f"{os_name}: {method['manager']}" for os_name, method in item.get("install", {}).items())
        custom = item.get("recipes", {})
        install_scripts = sum(r["action"] == "install" for r in custom.values())
        if install_scripts:
            methods += f"; {install_scripts} install script(s)"
        configs = ", ".join(item.get("configure", {}))
        other_scripts = len(custom) - install_scripts
        if other_scripts:
            configs += f"; {other_scripts} configure/workflow script(s)"
        description = item["description"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| [{item['name']}](../packages/{item['name']}/package.json) | {methods.strip('; ') or '—'} | {configs.strip('; ') or '—'} | {description} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    arguments = []
    if "--" in argv:
        delimiter = argv.index("--")
        arguments, argv = argv[delimiter + 1:], argv[:delimiter]
    args = parser().parse_args(argv)
    try:
        if arguments and args.action not in recipes.ACTIONS:
            raise SetupError("Arguments after -- require install/configure/run/remove. For setup use --install-arg or --configure-arg.")
        packages = load_catalog()
        if args.action == "validate":
            print(f"Validated {len(packages)} manifests and all referenced files. No commands executed.")
            return 0
        if args.action == "docs":
            rendered = index(packages)
            if args.check:
                if (ROOT / "docs/packages.md").read_text() != rendered:
                    raise SetupError("Package index is stale. Run: ./setup docs > docs/packages.md")
                print("Package index is current.")
            else:
                print(rendered, end="")
            return 0
        target = args.os or (detect_os() if args.action in {*recipes.ACTIONS, "setup"} else "all")
        if args.action in {"list", "search"}:
            items = [item for item in packages.values() if target == "all" or supports(item, target)]
            if args.action == "search":
                items = [item for item in items if args.query.casefold() in json.dumps(item).casefold()]
            if args.json:
                print(json.dumps(items, indent=2))
            else:
                for item in items:
                    methods = [f"{os_name}/{method['manager']}" for os_name, method in item.get("install", {}).items()
                               if target in {"all", os_name}]
                    label = ', '.join(methods) or ('named recipes' if item.get('recipes') else 'reference')
                    print(f"{item['name']:28} {label:38} {item['description']}")
                print(f"\n{len(items)} packages. Use ./setup show NAME --os OS for commands and setup references.")
            return 0 if items else 1
        item = resolve(packages, args.package)
        if args.action == "show":
            if args.source and not args.recipe:
                raise SetupError("--source requires --recipe NAME")
            if args.recipe:
                recipe = item.get("recipes", {}).get(args.recipe)
                if not recipe or (target != "all" and target not in recipe["os"]):
                    raise SetupError(f"Recipe {args.recipe} is unavailable for {target}")
                if args.source:
                    from .catalog import local_path
                    print(local_path(recipe["script"]).read_text(), end="")
                elif args.json:
                    print(json.dumps(recipe, indent=2))
                else:
                    recipes.describe(("script", recipe, args.recipe), [], {})
                return 0
            if target != "all" and not supports(item, target):
                raise SetupError(f"No {target} method or reference for {item['name']}. Try --os all.")
            if args.json:
                # Match the human view: only methods and references for the chosen OS.
                output = dict(item)
                for key in ("install", "configure"):
                    output[key] = {os_name: value for os_name, value in item.get(key, {}).items()
                                   if target in {"all", os_name}}
                output["references"] = selected_references(item, target)
                output["recipes"] = {key: value for key, value in item.get("recipes", {}).items()
                                     if target == "all" or target in value["os"]}
                print(json.dumps(output, indent=2))
            else:
                show(item, target)
            return 0
        if target not in SYSTEMS:
            raise SetupError(f"Unsupported execution OS '{target}'; specify one of {', '.join(SYSTEMS)} for a preview.")
        if args.action in {"run", "remove"} and not args.recipe:
            raise SetupError(f"{args.action} requires --recipe NAME. Use ./setup show {item['name']}.")
        phases = []
        for action in (("install", "configure") if args.action == "setup" else (args.action,)):
            choice = getattr(args, action + "_recipe", None) if args.action == "setup" else args.recipe
            operation = recipes.select(item, action, target, choice, optional=args.action == "setup")
            extra = getattr(args, action + "_arg", []) if args.action == "setup" else arguments
            if not operation and extra:
                raise SetupError(f"Cannot pass {action} arguments: no {action} phase exists for this package/OS")
            if operation:
                if extra and operation[0] != "script":
                    raise SetupError(f"Script arguments require an explicitly selected {action} script recipe")
                phases.append((action, operation, extra))
        if not phases:
            raise SetupError(f"No install/configure actions for {item['name']} on {target}; inspect named workflows with show.")
        parameters = {}
        declared = {key for _, op, _ in phases if op[0] == "script" for key in op[1]["parameters"]}
        for pair in args.parameters:
            key, separator, value = pair.partition("=")
            if not separator or key not in declared or key in parameters:
                raise SetupError(f"Unknown, duplicate, or malformed parameter: {key}. Declared: {', '.join(sorted(declared)) or 'none'}")
            parameters[key] = value
        for action, operation, extra in phases:
            print(f"{action.capitalize()} {item['name']} on {target}:", flush=True)
            recipes.describe(operation, extra, parameters)
        if not args.apply:
            print("Preview only. Nothing executed. Add --apply to run on the matching host OS.")
            return 0
        host = detect_os()
        if host != target:
            raise SetupError(f"Host is {host}; refusing to apply a {target} recipe.")
        installing = any(action == "install" for action, _, _ in phases)
        for action, operation, extra in phases:
            recipes.preflight(operation, extra, parameters, check_commands=not (installing and action == "configure"))
        for _, operation, extra in phases:
            recipes.preflight(operation, extra, parameters)
            recipes.execute(operation, extra, parameters, target)
        print("Done.")
        return 0
    except (SetupError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
