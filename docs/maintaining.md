# Maintaining the package catalog

The source of truth is `packages/<name>.json`. Do not add another bulk installer
or edit archived package arrays to introduce a new package.

## Add a package

Create a manifest using this structure (this example describes the existing Git
entry; use another name for a new package):

```json
{
  "name": "git",
  "description": "Distributed version control",
  "aliases": [],
  "install": {
    "ubuntu": {"manager": "apt", "package": "git"},
    "debian": {"manager": "apt", "package": "git"},
    "macos": {"manager": "brew", "package": "git"}
  },
  "configure": {
    "ubuntu": "git-aliases",
    "debian": "git-aliases",
    "macos": "git-aliases"
  },
  "references": [],
  "notes": []
}
```

`name` must match the filename. Aliases must be unique across the catalog. Choose
a user-facing name when OS package names differ: Docker uses `docker.io` on
Ubuntu/Debian and the `docker` cask on macOS. Aliases allow both names in the CLI.
Each OS maps to exactly one preferred install method. Preserve alternative or
historical methods as references instead of introducing ambiguous defaults.

| Manager | Package value | Allowed options | Apply requirements |
| --- | --- | --- | --- |
| `apt` | Distribution package name | none | `apt-get`, `dpkg-query`, `sudo` |
| `brew` | Formula or cask name | `--cask` | Existing Homebrew |
| `snap` | Snap name | `--classic`, `--edge` | Existing Snap and `sudo` |
| `pip` | Distribution name, optionally with extras/version | none | Active Python virtual environment with pip |
| `npm` | npm package name, including scoped names | none | Existing npm; global prefix must be writable |
| `go` | Module path with `@version` or `@latest` | none | Existing Go; binaries use its configured install directory |

Only declare OSes for which the method is appropriate. There is no implicit
fallback based on `ID_LIKE`, no manager installation, and no package availability
network call during discovery. Current manifests were extracted from earlier
scripts; availability is still release- and repository-dependent. Validate new
names with the relevant upstream package registry when changing them.

For a custom workflow that has not been migrated, omit `install` or leave it
empty and add a reference:

```json
{
  "path": "legacy/setup_server_linux/docker_setup.sh",
  "os": ["ubuntu", "debian"],
  "note": "Legacy Docker server configuration; inspect user, service, and storage settings."
}
```

Paths are relative to the repository root and must resolve to an existing file
inside it. Reference OSes may also include `macos`, `openwrt`, or `all`. References
are searchable and displayed but never executed. Add prerequisites and effects
to `note`; a reference does not certify compatibility or safety.

## Add configuration or manager support

Put reusable manager behavior in `setup_tool/managers.py`. Commands are argument
lists passed without a shell. Each invocation selects one package. Add tests
using fake executables; do not test by installing software on the development
machine.

Configuration recipes live in `setup_tool/configuration.py`; add their identifier
to the validator in `setup_tool/catalog.py`. Each recipe must have a complete
read-only preview, preserve existing user data, and behave sensibly on repeated
runs. Keep setup separate from installation. Test file writes under a temporary
home and mock network operations. Existing recipe identifiers are `git-aliases`,
`vim-filetypes`, and `tmux-plugins`.

## Validate and publish the index

```sh
./setup validate
python3 -m unittest discover -s tests -v
./setup docs > docs/packages.md
./setup docs --check
```

The test suite checks previews without subprocess execution, OS mismatch refusal,
single-package invocation, skip behavior, failure propagation, catalog integrity,
and preservation of configuration. No external Python packages are needed.

Keep the generated index in the same change as manifest edits. Archived shell
scripts are preserved historical code and are not covered by a blanket assertion
that every script is portable, current, or safe to run.
