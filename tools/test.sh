#!/bin/bash
# Runs the tests. Every test module names the host it needs (see tests/run.py).
#   tools/test.sh                 every module this machine can run
#   tools/test.sh --all           every module; fails if this machine lacks a host
#   tools/test.sh --list          what a run would take here, and why it would leave the others out
#   tools/test.sh tests.test_cli  the named modules; fails if this machine lacks their host
#   tools/test.sh --coverage      every module, then 100% branch coverage of src/sleep_control,
#                                 apart from the lines listed in tests/unreachable.tsv
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
# shellcheck source=tools/env.sh
. tools/env.sh
"$PYTHON" -c 'import PyQt6' 2>/dev/null || { echo "test: PyQt6 is missing, run tools/setup-dev.sh" >&2; exit 1; }
# The test process renders offscreen; the app processes it starts pick their own platform.
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src
if [ "${1:-}" != "--coverage" ]; then
  exec "$PYTHON" -m tests.run "$@"
fi
[ $# -eq 1 ] || { echo "test: --coverage takes no other arguments" >&2; exit 2; }
"$PYTHON" -c 'import coverage' 2>/dev/null || { echo "test: coverage is missing, run tools/setup-dev.sh" >&2; exit 1; }
data=$(mktemp -d)
trap 'rm -rf "$data"' EXIT
export COVERAGE_FILE="$data/coverage" COVERAGE_PROCESS_START="$root/tests/coveragerc"
"$PYTHON" -m coverage run --rcfile=tests/coveragerc -m tests.run --all
"$PYTHON" -m coverage combine --quiet --rcfile=tests/coveragerc
"$PYTHON" -m coverage json --quiet --rcfile=tests/coveragerc -o "$data/coverage.json"
"$PYTHON" -m tests.coverage_gate "$data/coverage.json" tests/unreachable.tsv
