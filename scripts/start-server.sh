#!/bin/bash
# Bootstrap and start the AgentCouncil MCP server.
# Tries uv (fastest, zero setup), falls back to venv+pip.
# macOS/Linux only. Windows support planned for a future release.

set -e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$PLUGIN_ROOT/.venv-data}"

# Option 1: uv is available — zero setup needed
if command -v uv &> /dev/null; then
    exec uv run --directory "$PLUGIN_ROOT" python -m agentcouncil.server
fi

# Option 2: fall back to venv + pip
VENV_DIR="$DATA_DIR/venv"
HASH_FILE="$DATA_DIR/pyproject.hash"

# Check prerequisites
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found on PATH. Install Python 3.12+ to use AgentCouncil." >&2
    exit 1
fi

if ! python3 -m venv --help &> /dev/null; then
    echo "ERROR: python3 venv module not available. Install python3-venv (e.g., apt install python3-venv)." >&2
    exit 1
fi

# Compute current dependency hash
CURRENT_HASH=""
if [ -f "$PLUGIN_ROOT/pyproject.toml" ]; then
    CURRENT_HASH=$(shasum -a 256 "$PLUGIN_ROOT/pyproject.toml" 2>/dev/null | cut -d' ' -f1)
fi

# Check if venv exists and dependencies are current
NEEDS_INSTALL=false
if [ ! -f "$VENV_DIR/bin/python3" ]; then
    NEEDS_INSTALL=true
elif [ -n "$CURRENT_HASH" ]; then
    STORED_HASH=$(cat "$HASH_FILE" 2>/dev/null || echo "")
    if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
        NEEDS_INSTALL=true
    fi
fi

if [ "$NEEDS_INSTALL" = true ]; then
    mkdir -p "$DATA_DIR"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python3" -m pip install --quiet -e "$PLUGIN_ROOT"
    echo "$CURRENT_HASH" > "$HASH_FILE"
fi

exec "$VENV_DIR/bin/python3" -m agentcouncil.server
