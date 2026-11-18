#!/usr/bin/env bash
# ==============================================================================
# 1-Click Desktop GUI Launcher for Annotators (Linux / macOS)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"

PYTHON_BIN="python3"
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif [ -f "$SCRIPT_DIR/../.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/../.venv/bin/python3"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -f "$VIRTUAL_ENV/bin/python3" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python3"
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/desktop_app.py"
