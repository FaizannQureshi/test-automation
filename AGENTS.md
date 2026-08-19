# test-automation

## Cursor Cloud specific instructions

This repository is currently a **stub**: the only tracked file is `README.md`. There is no
application code, package manifest (`package.json`, `pyproject.toml`, etc.), lockfile,
`Makefile`, `docker-compose`, `.devcontainer`, or `.cursor/environment.json`.

As a result there is nothing to install, lint, build, run, or test yet, and no services to
start. The Cloud Agent environment therefore uses a no-op update script.

Baseline toolchain available on the VM (for reference, not pinned by the repo): Node.js 22,
npm 10, Python 3.12, git 2.43.

When real code is added to this repository (e.g. an app plus its `package.json`/lockfile,
Dockerfile, or `docker-compose.yml`), re-run environment setup so the update script installs
the new dependencies and this section is updated with the actual lint/test/build/run commands
and services.
