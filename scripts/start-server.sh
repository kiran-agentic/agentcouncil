#!/bin/bash
# Bootstrap and start the AgentCouncil MCP server.
# Tries uv (fastest), falls back to venv+pip.

set -e

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# Option 1: uv is available — zero setup needed
if command -v uv &> /dev/null; then
    exec uv run --directory "$PLUGIN_ROOT" python -m agentcouncil.server
fi

# Option 2: fall back to venv + pip
VENV_DIR="$PLUGIN_ROOT/.venv"

if [ ! -f "$VENV_DIR/bin/python3" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet -e "$PLUGIN_ROOT"
fi

exec "$VENV_DIR/bin/python3" -m agentcouncil.server
