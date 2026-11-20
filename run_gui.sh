#!/usr/bin/env bash
# ==============================================================================
# 1-Click Desktop GUI Launcher for Annotators (Linux / macOS / WSL)
# Resolves the real installation directory even from symlinks or shortcuts.
# ==============================================================================
set -euo pipefail

# 1. Resolve real script location even if invoked via symlink from Desktop or bin
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

# 2. Fallback check: if desktop_app.py is missing here, check registered app path
if [ ! -f "$SCRIPT_DIR/desktop_app.py" ]; then
    CONFIG_PATH_FILE="$HOME/.config/nas_annotation/app_path"
    if [ -f "$CONFIG_PATH_FILE" ]; then
        RECORDED_PATH="$(cat "$CONFIG_PATH_FILE" | tr -d '\r\n')"
        if [ -f "$RECORDED_PATH/desktop_app.py" ]; then
            SCRIPT_DIR="$RECORDED_PATH"
        fi
    fi
fi

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

# 3. Locate Python executable (prefers virtualenv, then system)
PYTHON_BIN="python3"
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif [ -f "$SCRIPT_DIR/../.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/../.venv/bin/python3"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -f "$VIRTUAL_ENV/bin/python3" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python3"
fi

# Ensure requirements if venv exists but httpx missing
if [ -f "$SCRIPT_DIR/requirements_agent.txt" ]; then
    if ! "$PYTHON_BIN" -c "import httpx" 2>/dev/null; then
        echo "Installing missing client dependencies (httpx)..."
        "$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/requirements_agent.txt" --quiet || true
    fi
fi

# 4. Launch Desktop GUI application
exec "$PYTHON_BIN" "$SCRIPT_DIR/desktop_app.py" "$@"
