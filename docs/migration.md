# Migration from the script collection

Previously, installing a single package meant searching several arrays or finding
a script whose name did not consistently identify its OS. The new interface is
`./setup search`, `show`, `install`, and `configure`; the source of truth for
managed installs is `packages/*.json`.

| Previous entry point | New workflow |
| --- | --- |
| `install_packages/system_packages_install.sh` | `./setup install NAME --os ubuntu` or `--os macos` |
| `install_packages/python3_modules_install.sh` | Activate a virtual environment, then `./setup install NAME` |
| `install_packages/npm_packages_install.sh` | `./setup install NAME` |
| `install_packages/go_packages_install.sh` | `./setup install hover`, `sqls`, or `lux` |
| `setup_packages/NAME_setup.sh` | `./setup show NAME` for managed setup and legacy references |
| `install_and_setup_apps/*` | `./setup search NAME` and `./setup show NAME` |
| `setup_server_linux/*`, `setup_server_mac/*` | Search the workflow/package name; follow its legacy reference |
| `setup_Ubuntu_Mac.sh`, `minimal_setup.sh` | Select packages individually through the CLI |

Original files were moved, without changing their contents, to the same relative
paths under `legacy/`. Top-level compatibility symlinks preserve all old tracked
paths, including the existing Antigravity and Proxmox aliases. Directory symlinks
also preserve sibling references used by the old scripts. Keep these links until
you have migrated any external automation that depends on them.

Compatibility does not repair old assumptions: a script using a relative working
directory still needs that working directory, and pinned download URLs may have
expired. Existing server jobs were not executed or reconfigured during migration.
Raw GitHub links are a special case: GitHub serves the contents of a symlink as
text, so change raw-download URLs to the real `legacy/...` path. Git checkouts on
Linux and macOS follow the compatibility links normally.

The migration extracts package manager operations from bulk lists and separates
them from unrelated effects such as cloning dotfiles, installing Homebrew,
creating Java symlinks, and replacing Git configuration. Cask options are attached
to their package instead of being treated as another entry in an array.
Known historical or ambiguous recipes remain references. Most personal setup
scripts have not been rewritten; their manual-review status is explicit.

No package installations, real setup scripts, service changes, or remote downloads
are needed to validate the new CLI. Tests use fake package managers, mocked
network operations, and temporary configuration files.
