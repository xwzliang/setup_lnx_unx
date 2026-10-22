# Package setup for Linux and macOS

Find a package, choose an operating system, and preview exactly how to install or
configure it. The CLI uses Python 3.9+ and its standard library; there is nothing
to install to use this repository.

```sh
./setup search tmux
./setup list --os ubuntu
./setup show docker --os macos
./setup install tmux --os ubuntu           # preview; no commands executed
./setup install tmux --os ubuntu --apply   # install this package on Ubuntu
./setup configure tmux --os ubuntu        # preview its separate setup recipe
```

Start with the [package index](docs/packages.md) if you prefer browsing files.
Search includes names, aliases (for example `rg`, `chrome`, `sshd`), descriptions,
and paths to older setup scripts. `show` brings installation and configuration
information together for one package.

## Everyday use

| Task | Command |
| --- | --- |
| Search for a package on an OS | `./setup search python --os ubuntu` |
| See the available installation methods and setup scripts | `./setup show git` |
| See only macOS instructions | `./setup show git --os macos` |
| Preview a package installation for the current OS | `./setup install git` |
| Install the selected package | `./setup install git --apply` |
| Preview configuration separately | `./setup configure git` |
| Apply configuration separately | `./setup configure git --apply` |
| Find OpenWrt workflows | `./setup list --os openwrt` |
| Export search results for another tool | `./setup search editor --json` |
| Check the catalog without changing the machine | `./setup validate` |

`list`, `search`, and `show` default to all OSes. `install` and `configure` default
to the detected host OS. You can preview any supported OS from any machine, but
`--apply` requires an exact match. Ubuntu, Debian, and macOS have managed methods;
OpenWrt workflows are searchable references. Other distributions are not silently
treated as Ubuntu. Debian mappings are explicitly declared, not inherited from
Ubuntu.

Installation and configuration are separate actions. A package manager may
install dependencies of the selected package, but the CLI never invokes a bulk
installer, installs a missing package manager, updates the system package index,
or automatically runs personal setup scripts. `--dry-run` is an explicit synonym
for the default preview behavior, and never probes package managers or contacts
the network.

The selected package manager must already be available. APT and Snap use `sudo`;
Homebrew, npm, and Go run as your user. Python package methods use the interpreter
running the CLI and require an active virtual environment when applying. Activate
your environment before invoking `./setup`. No `sudo pip`, `--break-system-packages`,
or automatic environment creation is used.

APT, Homebrew, Snap, npm, and plain pip packages skip an already installed package
in that manager. pip extras/version requirements and Go `@version` requests are
passed to their respective resolvers rather than skipped based on a possibly
unrelated executable. Homebrew auto-update is disabled for installation.

## Configuration and older workflows

Managed configuration currently covers Git aliases, Vim filetype detection, and
the Tmux Plugin Manager checkout. Git preserves existing aliases and identity;
Vim uses a dedicated file and refuses conflicting contents; tmux preserves an
existing matching checkout. `./setup configure NAME` shows the exact scope.
TPM activation in your tmux configuration remains an explicit manual step.

Other setup instructions are linked by `./setup show NAME --os OS`. Entries marked
`reference` have no managed installation recipe yet. The original workflows are
preserved under [legacy/](legacy/README.md), including server, Docker, proxy,
OpenWrt, and personal desktop setup. Some contain pinned old downloads or personal
paths; inspect them before running. The CLI does not execute these scripts.

The catalog migrates this repository's installation knowledge; it is not a
guarantee that every package is available on every OS release. Read the notes
shown by `show`. For a missing package, check that release's repositories or
update its manifest. Remote installs were not performed to validate this redesign.

## Repository layout

```text
setup                   One entry point; run it directly from any working directory
packages/*.json         One manifest per package or discoverable workflow
setup_tool/             Catalog validation, CLI, package manager adapters, configuration
docs/packages.md        Generated package index
docs/maintaining.md     How to add or update a recipe
tests/                  Offline tests with fake package managers and temporary files
legacy/                 Original scripts and assets, with their original relative layout
```

Old top-level script and directory names are compatibility symlinks into `legacy/`.
They keep existing bookmarks and automation paths working; all new work belongs
in the structure above. See [migration details](docs/migration.md).

## Development

```sh
python3 -m unittest discover -s tests -v
./setup validate
./setup docs --check
```

These checks do not install packages. Add or change a package in one JSON file,
then regenerate the index with `./setup docs > docs/packages.md`. See the
[maintainer guide](docs/maintaining.md) for the manifest format and test strategy.
