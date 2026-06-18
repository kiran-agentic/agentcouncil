"""Tests for agentcouncil.host — host platform detection and host-aware defaults.

Covers:
    - detect_host() precedence: AGENTCOUNCIL_HOST > env markers > default "claude"
    - default_backend_for_host() clamping
    - host-aware defaults flowing into resolve_outside_backend / resolve_lead_backend
    - _make_provider("cursor") and resolve_lead_adapter("cursor") wiring
"""
from __future__ import annotations

import pytest

from agentcouncil.host import (
    DEFAULT_HOST,
    KNOWN_HOSTS,
    default_backend_for_host,
    detect_host,
)

# Every environment variable that can influence host detection. Cleared by the
# clean_host_env fixture so each test starts from a known-empty baseline,
# regardless of the host the test suite itself runs under.
_HOST_ENV_VARS = (
    "AGENTCOUNCIL_HOST",
    "AGENTCOUNCIL_OUTSIDE_AGENT",
    "AGENTCOUNCIL_LEAD_AGENT",
    "CODEX_PLUGIN_ROOT",
    "CODEX_HOME",
    "CODEX_SANDBOX",
    "CODEX_PLUGIN_DATA",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_PLUGIN_DATA",
)


@pytest.fixture
def clean_host_env(monkeypatch):
    """Clear all host-detection env vars; return monkeypatch for further setenv."""
    for var in _HOST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# detect_host()
# ---------------------------------------------------------------------------


def test_default_host_is_claude(clean_host_env):
    """No markers → historical default 'claude' (backward compatible)."""
    assert detect_host() == "claude"
    assert default_backend_for_host() == "claude"
    assert DEFAULT_HOST == "claude"


def test_explicit_agentcouncil_host_wins(clean_host_env):
    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    assert detect_host() == "cursor"


def test_explicit_host_is_normalized(clean_host_env):
    clean_host_env.setenv("AGENTCOUNCIL_HOST", "  Cursor ")
    assert detect_host() == "cursor"


def test_explicit_host_overrides_markers(clean_host_env):
    clean_host_env.setenv("CODEX_PLUGIN_ROOT", "/tmp/codex")
    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    assert detect_host() == "cursor"


def test_unknown_explicit_host_falls_through_to_markers(clean_host_env):
    clean_host_env.setenv("AGENTCOUNCIL_HOST", "vscode")
    assert detect_host() == "claude"  # falls through to default
    clean_host_env.setenv("CODEX_PLUGIN_ROOT", "/tmp/codex")
    assert detect_host() == "codex"  # falls through to marker


def test_codex_marker_detected(clean_host_env):
    clean_host_env.setenv("CODEX_PLUGIN_ROOT", "/tmp/codex")
    assert detect_host() == "codex"


def test_claude_marker_detected(clean_host_env):
    clean_host_env.setenv("CLAUDECODE", "1")
    assert detect_host() == "claude"


def test_codex_marker_precedes_claude_marker(clean_host_env):
    """Both marker families present → codex is checked first."""
    clean_host_env.setenv("CODEX_PLUGIN_ROOT", "/tmp/codex")
    clean_host_env.setenv("CLAUDE_PLUGIN_ROOT", "/tmp/claude")
    assert detect_host() == "codex"


# ---------------------------------------------------------------------------
# default_backend_for_host()
# ---------------------------------------------------------------------------


def test_default_backend_clamps_unknown_host():
    assert default_backend_for_host("weird-host") == "claude"


def test_default_backend_passes_through_known_host():
    assert default_backend_for_host("cursor") == "cursor"
    assert default_backend_for_host("codex") == "codex"


def test_all_known_hosts_are_valid_backends():
    from agentcouncil.adapters import VALID_BACKENDS, VALID_LEAD_BACKENDS

    for host in KNOWN_HOSTS:
        assert host in VALID_BACKENDS
        assert host in VALID_LEAD_BACKENDS


# ---------------------------------------------------------------------------
# Host-aware defaults flow through the resolvers
# ---------------------------------------------------------------------------


def test_outside_default_follows_host(clean_host_env):
    from agentcouncil.adapters import resolve_outside_backend

    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    assert resolve_outside_backend() == "cursor"


def test_outside_env_var_beats_host_default(clean_host_env):
    from agentcouncil.adapters import resolve_outside_backend

    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    clean_host_env.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "codex")
    assert resolve_outside_backend() == "codex"


def test_outside_explicit_arg_beats_host_default(clean_host_env):
    from agentcouncil.adapters import resolve_outside_backend

    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    assert resolve_outside_backend("claude") == "claude"


def test_lead_default_follows_host(clean_host_env):
    from agentcouncil.adapters import resolve_lead_backend

    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    assert resolve_lead_backend() == "cursor"


# ---------------------------------------------------------------------------
# Provider / adapter wiring for cursor
# ---------------------------------------------------------------------------


def test_make_provider_returns_cursor_provider(monkeypatch, clean_host_env):
    from agentcouncil.providers.cursor import CursorProvider
    from agentcouncil.server import _make_provider

    monkeypatch.setattr("agentcouncil.server.shutil.which", lambda x: "/usr/bin/" + x)
    provider = _make_provider("cursor")
    assert isinstance(provider, CursorProvider)


def test_resolve_lead_adapter_returns_cursor_adapter(monkeypatch):
    from agentcouncil.adapters import CursorAdapter, resolve_lead_adapter

    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
    adapter = resolve_lead_adapter("cursor")
    assert isinstance(adapter, CursorAdapter)


def test_make_lead_adapter_handles_cursor_host(clean_host_env):
    """Regression: server._make_lead_adapter (a factory separate from
    resolve_lead_adapter) must resolve a CursorAdapter on a Cursor host. It
    previously raised ValueError: Unknown lead backend: 'cursor', crashing every
    MCP protocol tool under default Cursor config."""
    from agentcouncil.adapters import CursorAdapter
    from agentcouncil.server import _make_lead_adapter

    clean_host_env.setattr("shutil.which", lambda x: "/usr/bin/" + x)
    clean_host_env.setenv("AGENTCOUNCIL_HOST", "cursor")
    adapter, provider, model = _make_lead_adapter(None)
    assert isinstance(adapter, CursorAdapter)
    assert provider == "cursor"


def test_resolve_outside_adapter_handles_cursor(monkeypatch):
    """Regression: the legacy resolve_outside_adapter fallback must cover cursor."""
    from agentcouncil.adapters import CursorAdapter, resolve_outside_adapter

    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
    adapter = resolve_outside_adapter("cursor")
    assert isinstance(adapter, CursorAdapter)
