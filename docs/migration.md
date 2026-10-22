# Migration to package-owned recipes

The initial catalog redesign is committed as `4d99aa9`. The next migration moves
all remaining implementation files out of `legacy/`: 129 files, including 119
executable recipes and their helper files/assets. Every package now owns a
`packages/<name>/package.json` manifest and a `scripts/` tree. The complete mapping
is [recipe-migration.json](recipe-migration.json).

`./setup show NAME` displays install methods, configuration variants, parameters,
effects, and source paths. `./setup setup NAME` plans installation followed by
configuration. Either phase can be selected alone, and `--recipe` (or
`--install-recipe`/`--configure-recipe`) selects alternatives. All commands preview
unless `--apply` is present.

Old top-level paths and paths beneath `legacy/` are compatibility symlinks to the
canonical files. They retain script filenames and executable permissions, but now
follow the updated implementations described below. For an exact historical copy,
use the initial redesign commit. Raw GitHub downloads must use canonical package
paths because raw endpoints return a symlink's text rather than following it.

## Behavior corrected during migration

- Cross-package workflows use canonical paths and the shared CLI. Bulk package
  profiles use the catalog instead of maintaining duplicate package arrays.
- The default workstation profile selects core tools explicitly; broad historical
  package lists remain explicitly named `run` workflows.
- Bash/Zsh initialization preserves existing files. Zsh does not change the login
  shell or invoke an installer that replaces `.zshrc`.
- Fish uses Fisher's current install interface and standard curl, removing the
  dependency on personal proxy shell functions. See the
  [upstream Fisher instructions](https://github.com/jorgebucaran/fisher#installation).
- Git, Vim, and tmux script entry points delegate to their narrower built-in
  configuration recipes.
- Samba, fstab mounts, certificate setup, Coursera credentials, and Zotero profile
  setup take explicit account/path inputs instead of silently using fixed values.
- Cron preserves existing jobs and does not disable system updates. Lid settings
  use a logind drop-in. ImageMagick retains policy restrictions for other coders.
- APT mirror setup preserves release suites and unrelated repositories. Proxy
  configuration handles Homebrew's prefix and keeps a backup.
- Package-owned helpers stay beside their callers. Shell recipes stop after command
  failures; a failed installation prevents its following configuration phase.

Some specialized historical scripts still have release-specific downloads, hardware
assumptions, native root requirements, or upstream compatibility limitations. Their
source and effects are exposed in `show`; migration does not certify that every
upstream installer works on every current OS release. No real package installation
or system-changing recipe was run to validate this change.

OpenWrt scripts retain their shell interpreter. Running the CLI on an OpenWrt host
requires Python 3.9+ already installed; the migration does not bootstrap it.
