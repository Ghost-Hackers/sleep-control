# shellcheck shell=bash
# Sourced by the other tools: picks the Python that has the dev tools.
# $PYTHON wins, then the repo's .venv, then python3 on PATH. Needs $root set.
: "${root:?}"
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$root/.venv/bin/python" ]; then PYTHON="$root/.venv/bin/python"; else PYTHON=python3; fi
fi
bindir=$(dirname "$(command -v "$PYTHON")")
export PATH="$bindir:$PATH"
