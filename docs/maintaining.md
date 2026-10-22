# Maintaining packages and recipes

Each package has one home: `packages/<name>/package.json` and sibling scripts or
assets. Names must match directory names. Aliases are unique across the catalog.
Avoid new bulk installers; use explicit workflow recipes for intentional profiles.

## Native methods and built-in configuration

An `install` object maps OS names to one preferred manager method:

```json
"install": {
  "ubuntu": {"manager": "apt", "package": "docker.io"},
  "macos": {"manager": "brew", "package": "docker", "options": ["--cask"]}
}
```

Supported managers: `apt`, `brew`, `snap`, `pip`, `npm`, `go`. Options are restricted
to `--cask` for Brew and `--classic`/`--edge` for Snap. Managers must already exist;
pip requires an active virtual environment. OS mappings are explicit, with no
Ubuntu inheritance for derivatives. Validate changed package names against the
relevant upstream registry.

`configure` maps OS names to built-in identifiers: `git-aliases`, `vim-filetypes`,
`tmux-plugins`. These are narrow, repeatable operations in
`setup_tool/configuration.py`. Native install methods and built-in configuration
win over script defaults; `--recipe` explicitly selects a script alternative.

## Script recipes

Add a named entry under `recipes`:

```json
"recipes": {
  "configure-share": {
    "action": "configure",
    "os": ["ubuntu", "debian"],
    "script": "packages/example/scripts/configure.sh",
    "interpreter": "bash",
    "description": "Configure a named share",
    "effects": "Adds a dedicated share and restarts its service; preserves other shares.",
    "requires": ["python3", "sudo"],
    "parameters": {
      "SHARE_PATH": {"description": "Absolute directory to share", "required": true}
    }
  }
},
"defaults": {"configure": {"ubuntu": "configure-share", "debian": "configure-share"}}
```

Actions are `install`, `configure`, `run`, or `remove`. Only install/configure may
have defaults. `run` and `remove` always require explicit selection. Defaults must
point to a recipe supporting the same action and OS. Multiple alternatives without
a default are an error, never an invitation to run every recipe.

Scripts must resolve inside their owning package directory. Interpreters are
`bash` (with `-e -o pipefail`), `sh` (with `-e`), or `python3` (the CLI interpreter).
The working directory is the script's parent, so sibling assets remain local.
Avoid depending on the caller's working directory or personal shell functions.

A parameter may have a `default` string and/or `required: true`. The CLI validates
keys, rejects unknown or duplicate values, and passes declared values as
`SETUP_<NAME>`. Use those values as data and quote them inside scripts. Reserved
runtime variables are `SETUP_REPO_ROOT`, `SETUP_PYTHON`, and `SETUP_OS`.

Optional `arguments` metadata declares positional inputs:

```json
"arguments": {"minimum": 3, "usage": "HOST PORT UUID [ALTER_ID]"}
```

Arguments after `--` pass unchanged to one script. Combined setup uses
`--install-arg=VALUE` or `--configure-arg=VALUE` instead. Never interpret arguments
with `eval` or `shell=True`. Scripts retaining Bash 4 features must declare
`bash_min_version: 4`; macOS's bundled Bash may be older.

Required inputs and the complete action selection are checked before any phase
runs. Command prerequisites are rechecked immediately before execution. For
combined setup, configuration prerequisites are deferred until after installation
because the package may supply them. Do not promise atomic rollback across phases.

A `references` array can link related source files or assets, but executable
scripts belong in `recipes`. References are not executed implicitly. `notes`
should explain release restrictions, pinned versions, remaining manual steps,
and prerequisites that cannot be checked mechanically.

## Maintenance checks

```sh
./setup validate
python3 -m unittest discover -s tests -v
./setup docs > docs/packages.md
./setup docs --check
```

Tests must not install software. Use fixture executables, temporary configurations,
and mocked downloads. The suite previews every catalog recipe without allowing
subprocesses, parses shell/Python code, checks migration links and complete script
coverage, and exercises phase ordering and failure handling with temporary scripts.

The complete relocation map is `docs/recipe-migration.json`. Keep compatibility
symlinks and their map entries current when moving files. Preserve sibling helper
files (such as account-monitor tests and IINA's repository list). New implementation
work belongs under the package; `legacy/` now contains only compatibility paths.
