#!/bin/bash
# Bootstrap and start the AgentCouncil MCP server.
# Tries uv (fastest, zero setup), falls back to venv+pip.
# Self-verifying: a partial/interrupted install is detected and repaired instead
# of crashing the server with a cryptic "No module named 'rich'/'fastmcp'".
# macOS/Linux only. Windows support planned for a future release.

set -e

# Resolve the repo root from this script's own location ($0), so the launcher works
# regardless of any host-specific plugin-root variable. Cursor launches plugin MCP
# commands with a relative path from the plugin root and sets no CLAUDE_PLUGIN_ROOT,
# so SCRIPT_ROOT is the reliable anchor; the *_PLUGIN_ROOT vars are honored when present.
SCRIPT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_ROOT="${AGENTCOUNCIL_PLUGIN_ROOT:-${CURSOR_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$SCRIPT_ROOT}}}}"
DATA_DIR="${AGENTCOUNCIL_PLUGIN_DATA:-${CURSOR_PLUGIN_DATA:-${CODEX_PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-$PLUGIN_ROOT/.venv-data}}}}"

# Modules the server cannot start without. fastmcp pulls in rich (rich.traceback),
# pydantic, etc. — importing these is the real proof the env is usable.
DEP_CHECK="import fastmcp, rich.traceback, pydantic"

# ---------------------------------------------------------------------------
# Option 1: uv (fastest). Search common install dirs too — an MCP host (e.g.
# Cursor) may launch us with a minimal PATH that omits ~/.local/bin, ~/.cargo/bin.
# ---------------------------------------------------------------------------
UV_BIN="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV_BIN" ]; then
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
        if [ -x "$candidate" ]; then UV_BIN="$candidate"; break; fi
    done
fi
if [ -n "$UV_BIN" ]; then
    # `uv run` auto-syncs missing packages, but it won't repair files it believes are
    # already installed (a corrupt/partial .venv). Verify the env directly and force a
    # sync (then a reinstall) only when the dep check fails, so a broken or fresh env
    # self-heals without paying a full sync on every launch.
    UV_VENV_PY="$PLUGIN_ROOT/.venv/bin/python"
    if ! { [ -x "$UV_VENV_PY" ] && "$UV_VENV_PY" -c "$DEP_CHECK" > /dev/null 2>&1; }; then
        "$UV_BIN" sync --directory "$PLUGIN_ROOT" --quiet 1>&2 2>/dev/null || true
        if ! { [ -x "$UV_VENV_PY" ] && "$UV_VENV_PY" -c "$DEP_CHECK" > /dev/null 2>&1; }; then
            "$UV_BIN" sync --directory "$PLUGIN_ROOT" --reinstall --quiet 1>&2 2>/dev/null || true
        fi
    fi
    exec "$UV_BIN" run --directory "$PLUGIN_ROOT" python -m agentcouncil.server
fi

# ---------------------------------------------------------------------------
# Option 2: venv + pip
# ---------------------------------------------------------------------------
VENV_DIR="$DATA_DIR/venv"
VENV_PY="$VENV_DIR/bin/python3"
HASH_FILE="$DATA_DIR/pyproject.hash"

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found on PATH. Install Python 3.12+ (or uv) to use AgentCouncil." >&2
    exit 1
fi
if ! python3 -m venv --help &> /dev/null; then
    echo "ERROR: python3 venv module not available. Install python3-venv (e.g., apt install python3-venv)." >&2
    exit 1
fi

# True only if the venv exists AND its dependencies actually import. This is what
# makes the bootstrap self-healing: a venv left half-built by an interrupted first
# install (or a stale/incompatible one) fails this check and gets repaired.
deps_ok() { [ -x "$VENV_PY" ] && "$VENV_PY" -c "$DEP_CHECK" > /dev/null 2>&1; }

CURRENT_HASH=""
if [ -f "$PLUGIN_ROOT/pyproject.toml" ]; then
    CURRENT_HASH=$(shasum -a 256 "$PLUGIN_ROOT/pyproject.toml" 2>/dev/null | cut -d' ' -f1)
fi

NEEDS_INSTALL=false
if ! deps_ok; then
    NEEDS_INSTALL=true   # missing venv OR incomplete deps (e.g. interrupted install)
elif [ -n "$CURRENT_HASH" ] && [ "$CURRENT_HASH" != "$(cat "$HASH_FILE" 2>/dev/null || echo "")" ]; then
    NEEDS_INSTALL=true   # pyproject changed since last install
fi

if [ "$NEEDS_INSTALL" = true ]; then
    mkdir -p "$DATA_DIR"
    [ -x "$VENV_PY" ] || python3 -m venv "$VENV_DIR"
    # pip output goes to stderr so it never corrupts the MCP stdio (JSON-RPC) stream.
    "$VENV_PY" -m pip install --quiet --upgrade pip 1>&2 2>/dev/null || true
    if ! "$VENV_PY" -m pip install --quiet -e "$PLUGIN_ROOT" 1>&2; then
        echo "ERROR: failed to install AgentCouncil dependencies into $VENV_DIR." >&2
        echo "Fix: install 'uv' (https://docs.astral.sh/uv/), or run: rm -rf \"$DATA_DIR\" and relaunch." >&2
        exit 1
    fi
    if ! deps_ok; then
        echo "ERROR: AgentCouncil installed but core modules (fastmcp/rich/pydantic) are missing." >&2
        echo "Fix: run: rm -rf \"$DATA_DIR\" and relaunch, or install 'uv' (https://docs.astral.sh/uv/)." >&2
        exit 1
    fi
    echo "$CURRENT_HASH" > "$HASH_FILE"
fi

exec "$VENV_PY" -m agentcouncil.server
