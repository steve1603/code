#!/bin/bash
# SessionStart hook — installs everything tests/linters/autofix need.
# Only runs in Claude Code on the web; a no-op locally.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# 1) Python deps (PySide6, pypdf). pip install is idempotent.
if [ -f requirements.txt ]; then
    PIP_ROOT_USER_ACTION=ignore \
        python -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

# 2) Qt runtime libraries so PySide6 can import headless. Needed for any
#    check that instantiates a QApplication (e.g. autofix verifying GUI
#    modules still import after a change).
if command -v apt-get >/dev/null 2>&1; then
    SUDO=""
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 && SUDO="sudo -n"
    fi
    # Swallow errors if we can't sudo — the core (non-GUI) tests still work.
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends \
        libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1 \
        >/dev/null 2>&1 || echo "note: could not install Qt runtime libs (headless GUI checks may fail)"
fi

# 3) Qt needs a platform plugin; offscreen works without a display.
echo 'export QT_QPA_PLATFORM=offscreen' >> "$CLAUDE_ENV_FILE"

echo "session-start: dependencies ready"
