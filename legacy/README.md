# Original scripts

This directory preserves the original repository layout and script contents.
Start with [`../setup`](../setup) and the [package index](../docs/packages.md) for
single-package installation and setup discovery.

| Directory | Contents |
| --- | --- |
| `install_packages/` | Original bulk package arrays and language tool installers |
| `install_and_setup_apps/` | Custom application installers and removal scripts |
| `setup_packages/` | Personal shell, editor, proxy, keyboard, and system settings |
| `setup_server_linux/` | Linux server and container workflows |
| `setup_server_mac/` | macOS server and container workflows |
| `setup_proxy/` | Proxy workflows and supporting assets |
| `openwrt/`, `setup_openwrt/` | Router workflows |

These scripts may install multiple packages, change services, overwrite personal
configuration, or depend on old releases and hardcoded paths. They are references,
not automatically executed extensions of the new CLI. Read a script and its
prerequisites before running it manually; preserve any working-directory
assumptions it makes. Top-level compatibility symlinks keep the previous paths
available for existing automation.
