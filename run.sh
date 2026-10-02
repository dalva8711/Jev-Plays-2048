#!/usr/bin/env bash
# Jev plays 2048 - setup and launch script.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

exec ./.venv/bin/python -m jev2048.main
