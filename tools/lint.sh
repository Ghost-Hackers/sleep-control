#!/bin/bash
# Lints the Python code with Ruff, type-checks it with Pyright and lints the shell scripts with ShellCheck.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
# shellcheck source=tools/env.sh
. tools/env.sh
command -v ruff >/dev/null || { echo "lint: ruff is missing, run tools/setup-dev.sh" >&2; exit 1; }
command -v pyright >/dev/null || { echo "lint: pyright is missing, run tools/setup-dev.sh" >&2; exit 1; }
command -v shellcheck >/dev/null || { echo "lint: shellcheck is missing, run tools/setup-dev.sh" >&2; exit 1; }
ruff check src tests
# --pythonpath finds PyQt6 also where the tree has no .venv, as in the guard's staged copy.
pyright --pythonpath "$(command -v "$PYTHON")"
shopt -s nullglob
shellcheck -x tools/*.sh tests/e2e/*.sh packaging/flatpak/*.sh .github/scripts/*.sh .guard/*/*.sh
echo "lint: ruff, pyright and shellcheck clean"
