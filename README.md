# Package setup for Linux and macOS

Search, install, and configure a package from one place. Each package owns its
manifest, scripts, and supporting files under `packages/<name>/`. The CLI requires
Python 3.9+ and only its standard library; no dependency installation is needed.

```sh
./setup search zsh
./setup show zsh --os ubuntu
./setup setup zsh --os ubuntu           # preview installation AND configuration
./setup setup zsh --os ubuntu --apply   # execute both on an Ubuntu host
```

Nothing runs without `--apply`. Browse the [package index](docs/packages.md) or
use `./setup show NAME` to see every method, recipe, parameter, and source path.

## Install and configure together or separately

| Task | Command |
| --- | --- |
| Preview both phases | `./setup setup git --os ubuntu` |
| Install only | `./setup install git --os ubuntu` |
| Configure only | `./setup configure git --os ubuntu` |
| List packages for an OS | `./setup list --os macos` |
| Search names, aliases, descriptions, and source paths | `./setup search chrome` |
| Inspect configuration alternatives | `./setup show keyboard --os ubuntu` |
| Choose a configuration variant | `./setup configure keyboard --recipe xmodmap-setup-win-keyboard --os ubuntu` |
| Inspect a recipe's code | `./setup show zsh --recipe zsh-setup --source` |
| Select an alternative installer | `./setup install docker --recipe docker-setup --os ubuntu` |
| Select an alternative in a combined setup | `./setup setup docker --install-recipe docker-setup --os ubuntu` |
| Preview an explicit workflow | `./setup run mac-server --recipe start-server --os macos` |
| Preview removal | `./setup remove zotero --recipe zotero-uninstall --os ubuntu` |

Append `--apply` when ready to execute. `--dry-run` explicitly selects the default
preview behavior. Previewing does not probe package managers, run scripts, write
configuration, or contact the network.

`setup` plans all available install/configure phases before doing anything. It
uses the package manager method and narrow built-in configuration when available,
otherwise the manifest's default script. Multiple alternatives without a declared
default require a recipe choice. Missing phases are skipped, so a configuration-only
package such as `keyboard` can use `setup` too. Workflows and removal are always
separate, explicitly selected operations.

## Package-specific inputs

Machine-specific recipes declare their inputs. For example:

```sh
./setup setup samba --os ubuntu \
  --set SMB_USER=myuser --set SMB_PATH=/srv/share

./setup configure mounts --os ubuntu \
  --set FSTAB_FILE=/absolute/path/to/reviewed-fstab-entries

./setup configure zotero --os ubuntu \
  --set ZOTERO_PROFILE=/absolute/path/to/profile \
  --set ATTACHMENT_DIR=/absolute/path/to/attachments
```

`show` lists required parameters. Missing required values prevent execution of
**both** phases, including installation. Parameters are passed as namespaced
`SETUP_*` environment values, never evaluated as shell text. Passwords are prompted
by the relevant configuration script rather than stored in manifests.

Script arguments go after `--`, preserving the script's native interface:

```sh
./setup configure proxmox-autologin --os debian \
  --recipe setup-proxmox-autologin -- --remote root@pve
```

For `setup`, use repeated `--install-arg=VALUE` and `--configure-arg=VALUE` to select
the receiving phase. These require a script method; package manager methods do
not accept arbitrary extra arguments. To execute a script's native `--help`, use
`--apply -- --help` (the CLI's preview intentionally never executes even help).

## Operating systems and execution

Discovery defaults to all OSes; actions default to the exact detected host OS.
You may preview another OS but cannot apply it to a mismatched host. Ubuntu,
Debian, and macOS have package methods and script recipes. OpenWrt has explicit
shell workflows; running the CLI there still requires an existing Python 3.9+.
Other distributions are not silently treated as Ubuntu.

Package manager methods install one selected package plus its dependencies.
APT and Snap use `sudo`; Homebrew, npm, and Go use your account. The manager must
already exist. Python package methods require an active virtual environment.
APT, Brew, Snap, npm, and plain pip packages skip installed packages; pip extras
and Go version requests are resolved by their respective tools.

Custom scripts can install dependencies, fetch plugins, edit system settings,
restart services, or perform the workflow described in their `effects` field.
Bash recipes run with error and pipeline failure handling, in their own directory.
An error stops later phases; changes already made are not automatically rolled
back. Inputs and OS selection are checked before installation; configuration
executables are checked again after installation because the package may provide
them. Scripts that require root retain their native privilege handling; read the
source or help for specialized administration tasks.

The migration preserves historical installation methods, including some pinned
versions and upstream downloads. These have not been tested with live installations
on every OS or checked for current upstream availability. The new structure makes
those recipes discoverable and maintainable without claiming universal portability.

## Repository layout

```text
setup                           CLI entry point
packages/<name>/package.json     Install methods, configuration, recipes, parameters
packages/<name>/scripts/         Package-owned scripts and sibling assets
setup_tool/                     Planning, validation, execution, manager adapters
tests/                          Offline tests (no real installations)
docs/packages.md                Generated package index
docs/recipe-migration.json       Historical old-path to current-path mapping
```

Use `./setup` and the package-owned files; the legacy folder and root compatibility
links have been removed. The migration checkpoint is commit `6f4f6d1`, and the
original scripts are preserved in `4d99aa9` under `legacy/`.
[Migration details](docs/migration.md) explain the behavioral changes;
[maintaining the catalog](docs/maintaining.md) covers new recipes.

## Validation without installing packages

```sh
python3 -m unittest discover -s tests -v
./setup validate
./setup docs --check
```

Tests cover every recipe's preview, syntax, migration coverage, parameter and OS
checks, ordered execution using temporary fixtures, and configuration preservation.
No real installer, download, or service-changing workflow is run by these checks.
After a manifest edit, regenerate the index with `./setup docs > docs/packages.md`.
