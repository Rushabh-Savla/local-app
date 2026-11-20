#!/usr/bin/env bash
# ==============================================================================
# 1-Click Desktop Icon Installer for Linux / macOS Workstations
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

chmod +x "$SCRIPT_DIR/run_gui.sh"
chmod +x "$SCRIPT_DIR/setup_desktop_icon.py"

PYTHON_BIN="python3"
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
fi

"$PYTHON_BIN" "$SCRIPT_DIR/setup_desktop_icon.py"
