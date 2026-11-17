#!/bin/bash
# Creates .venv with the pinned test and lint tools from requirements-dev.txt.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-dev.txt
echo "setup-dev: .venv ready ($(.venv/bin/python --version))"
