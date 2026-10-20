#!/usr/bin/env bash
# ==============================================================================
# Central Annotator Agent Launcher
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR"

# Load .env strictly if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

SERVER_URL="${SERVER_URL:-}"
ROOT="${ROOT:-$HOME/nas_annotation_workspace}"

# Detect and use virtualenv if available
PYTHON_BIN="python3"
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif [ -f "$SCRIPT_DIR/../.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/../.venv/bin/python3"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -f "$VIRTUAL_ENV/bin/python3" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python3"
fi

echo "Starting Annotator Desktop Agent using $PYTHON_BIN..."
"$PYTHON_BIN" -m annotator_agent.agent --server-url "$SERVER_URL" --local-root "$ROOT" "$@"

