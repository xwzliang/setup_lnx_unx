# Compatibility paths

Implementation files have moved to `packages/<name>/scripts/`. This directory now
contains compatibility symlinks so existing checkout paths still resolve. Edit the
canonical package files instead of these links.

Use `../setup show NAME` to inspect package methods and named recipes, and
`../setup setup NAME` to preview installation and configuration together.
Add `--apply` only when you intend to execute the previewed changes.

See the [migration guide](../docs/migration.md) and the complete
[path mapping](../docs/recipe-migration.json). Exact historical script contents
remain available in commit `4d99aa9`; compatibility links follow updated code.
