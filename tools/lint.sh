#!/bin/bash
# Lints the Python code with Ruff and the shell scripts with ShellCheck.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
# shellcheck source=tools/env.sh
. tools/env.sh
command -v ruff >/dev/null || { echo "lint: ruff is missing, run tools/setup-dev.sh" >&2; exit 1; }
command -v shellcheck >/dev/null || { echo "lint: shellcheck is missing, run tools/setup-dev.sh" >&2; exit 1; }
ruff check src tests
shopt -s nullglob
shellcheck -x tools/*.sh tests/e2e/*.sh packaging/flatpak/*.sh .github/scripts/*.sh .guard/*/*.sh
echo "lint: ruff and shellcheck clean"
