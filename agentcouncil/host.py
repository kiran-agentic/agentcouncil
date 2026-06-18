"""agentcouncil.host — Detect which host agent platform AgentCouncil runs under.

The *host* is the agent runtime that loads AgentCouncil's skills and launches its
MCP server: Claude Code, Codex, or Cursor. The host determines the zero-config
default backend — "the backend it runs on". On Claude Code the default outside
agent is Claude; on Codex it is Codex; on Cursor it is Cursor. In every case the
outside agent is still a *separate, independent session* from the host (same-family
fresh session — see docs/BACKENDS.md "Independence Tiers").

Detection precedence (highest first):

    1. ``AGENTCOUNCIL_HOST`` env var — explicit override. Each platform's MCP
       launch config sets this; e.g. ``.cursor/mcp.json`` sets it to ``"cursor"``.
    2. Auto-detection from platform-native markers that the host injects into the
       MCP server process environment:
         - ``CODEX_PLUGIN_ROOT`` / ``CODEX_HOME`` / ``CODEX_SANDBOX``  → ``"codex"``
         - ``CLAUDE_PLUGIN_ROOT`` / ``CLAUDECODE`` / ``CLAUDE_CODE_*`` → ``"claude"``
       Cursor exposes no reliable host-only marker, so Cursor is recognised only
       via the explicit ``AGENTCOUNCIL_HOST`` set by the shipped ``.cursor/mcp.json``.
       (We deliberately do NOT sniff ``CURSOR_API_KEY`` — a user may set it to run
       ``cursor-agent`` as a *backend* while hosted in Claude Code or Codex.)
    3. Default ``"claude"`` — the historical built-in default, so behaviour is
       unchanged anywhere a host cannot be identified (e.g. plain unit tests).
"""
from __future__ import annotations

import os

__all__ = [
    "KNOWN_HOSTS",
    "DEFAULT_HOST",
    "detect_host",
    "default_backend_for_host",
]

# Host platforms AgentCouncil knows how to run under. Each name is also a valid
# backend name (see adapters.VALID_BACKENDS), so the host doubles as the
# zero-config default backend.
KNOWN_HOSTS: tuple[str, ...] = ("claude", "codex", "cursor")

# Backward-compatible fallback when no host can be identified.
DEFAULT_HOST = "claude"

# Environment markers each host injects into the MCP server's environment.
# Checked in order; first match wins. Cursor is intentionally absent — it has no
# reliable host-only marker, so it relies on the explicit AGENTCOUNCIL_HOST that
# the shipped .cursor/mcp.json sets.
_HOST_ENV_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("codex", ("CODEX_PLUGIN_ROOT", "CODEX_HOME", "CODEX_SANDBOX", "CODEX_PLUGIN_DATA")),
    ("claude", ("CLAUDE_PLUGIN_ROOT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PLUGIN_DATA")),
)


def detect_host() -> str:
    """Return the detected host platform: ``"claude"``, ``"codex"`` or ``"cursor"``.

    Never raises. An unrecognised explicit ``AGENTCOUNCIL_HOST`` value is ignored
    (falls through to auto-detection) rather than crashing the server.
    """
    explicit = os.environ.get("AGENTCOUNCIL_HOST")
    if explicit:
        normalized = explicit.strip().lower()
        if normalized in KNOWN_HOSTS:
            return normalized
        # Unknown explicit value — ignore and fall through to auto-detection.

    for host, markers in _HOST_ENV_MARKERS:
        if any(os.environ.get(marker) for marker in markers):
            return host

    return DEFAULT_HOST


def default_backend_for_host(host: str | None = None) -> str:
    """Return the zero-config default backend for the given (or detected) host.

    The host name *is* the backend name for all known hosts. If the host is
    somehow not a valid backend, fall back to the historical ``"claude"`` default.
    """
    resolved = host or detect_host()
    return resolved if resolved in KNOWN_HOSTS else DEFAULT_HOST
