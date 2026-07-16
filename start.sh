#!/usr/bin/env bash
# One-command launcher for the finadvisor web UI.
#
#   ./start.sh                 # start on http://127.0.0.1:8765
#   ./start.sh --port 9000     # any extra args pass through to the server
#
# First run creates a .venv/ and installs pypdf (for PDF statement
# import). PySide6 is NOT required — the web UI is stdlib-only.
set -euo pipefail
cd "$(dirname "$0")"

# 1) Find a Python 3.10+ interpreter.
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
            PY="$cand"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    echo "error: Python 3.10+ not found. Install it from https://python.org" >&2
    exit 1
fi

# 2) Create the virtualenv on first run.
if [ ! -d .venv ]; then
    echo "First run — creating virtual environment..."
    "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) Install pypdf if missing (only dependency the web UI can use;
#    it powers PDF statement import — everything else is stdlib).
if ! python -c 'import pypdf' >/dev/null 2>&1; then
    echo "Installing pypdf (PDF statement import)..."
    pip install --quiet "pypdf>=4.0"
fi

# 4) Launch. Data persists to ./finances.json next to this script.
echo
echo "Starting finadvisor — open the URL printed below in your browser."
echo "(Ctrl+C stops the server. Your data lives in ./finances.json)"
echo
exec python -m finadvisor.web "$@"
