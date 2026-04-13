"""Tests for backend resolver and configuration precedence.

Covers:
    BACK-01..06: Backend resolver returns correct adapter types
    TEST-01: resolve_outside_adapter returns correct types per backend
    TEST-02: Config precedence (arg > env > default)
    TEST-03: Transcript metadata populated correctly
"""
from __future__ import annotations

import pytest

from agentcouncil.adapters import (
    ClaudeAdapter,
    CodexAdapter,
    resolve_outside_adapter,
    resolve_outside_backend,
)
from agentcouncil.schemas import TranscriptMeta


# ---------------------------------------------------------------------------
# resolve_outside_backend tests
# ---------------------------------------------------------------------------


def test_backend_default_is_claude(monkeypatch):
    """UFALL-01: Default backend is claude when no arg or env var."""
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    assert resolve_outside_backend() == "claude"


def test_backend_arg_overrides_env(monkeypatch):
    """BACK-03: Explicit arg takes precedence over env var."""
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "codex")
    assert resolve_outside_backend("claude") == "claude"


def test_backend_env_var_used_when_no_arg(monkeypatch):
    """BACK-02: Env var used when no explicit arg."""
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "claude")
    assert resolve_outside_backend() == "claude"


def test_backend_arg_overrides_everything(monkeypatch):
    """BACK-03: Arg > env > default."""
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "codex")
    assert resolve_outside_backend("claude") == "claude"


# ---------------------------------------------------------------------------
# resolve_outside_adapter tests
# ---------------------------------------------------------------------------


def test_resolver_codex_returns_codex_adapter(monkeypatch):
    """BACK-04, TEST-01: codex backend returns CodexAdapter."""
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
    adapter = resolve_outside_adapter("codex", timeout=120)
    assert isinstance(adapter, CodexAdapter)


def test_resolver_claude_returns_claude_adapter(monkeypatch):
    """BACK-04, BACK-05, TEST-01: claude backend returns ClaudeAdapter (no new class)."""
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
    adapter = resolve_outside_adapter("claude", timeout=120)
    assert isinstance(adapter, ClaudeAdapter)


def test_resolver_unknown_backend_raises():
    """BACK-04: Unknown backend raises ValueError."""
    with pytest.raises(ValueError, match="Unknown outside agent backend"):
        resolve_outside_adapter("openai", timeout=120)


def test_backend_resolver_rejects_invalid(monkeypatch):
    """AC-01: Invalid backend values fail fast at resolution, not silently routed."""
    with pytest.raises(ValueError, match="Unknown outside agent backend"):
        resolve_outside_backend("typo")


def test_backend_resolver_rejects_invalid_env(monkeypatch):
    """AC-01: Invalid env var values fail fast."""
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "openai")
    with pytest.raises(ValueError, match="Unknown outside agent backend"):
        resolve_outside_backend()


def test_resolver_uses_env_var_when_no_arg(monkeypatch):
    """BACK-02, TEST-02: Env var fallback works for resolver."""
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/" + x)
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "claude")
    adapter = resolve_outside_adapter(timeout=120)
    assert isinstance(adapter, ClaudeAdapter)


# ---------------------------------------------------------------------------
# TranscriptMeta tests
# ---------------------------------------------------------------------------


def test_meta_cross_backend():
    """META-03: Different backends produce cross_backend tier."""
    meta = TranscriptMeta(
        lead_backend="claude",
        outside_backend="codex",
        independence_tier="cross_backend",
    )
    assert meta.independence_tier == "cross_backend"


def test_meta_same_backend():
    """META-03: Same backend produces same_backend_fresh_session tier."""
    meta = TranscriptMeta(
        lead_backend="claude",
        outside_backend="claude",
        independence_tier="same_backend_fresh_session",
    )
    assert meta.independence_tier == "same_backend_fresh_session"


def test_meta_serialization():
    """META-01..03: TranscriptMeta round-trips through JSON."""
    meta = TranscriptMeta(
        lead_backend="claude",
        lead_model="opus",
        outside_backend="codex",
        outside_model=None,
        outside_transport="subprocess",
        independence_tier="cross_backend",
    )
    data = meta.model_dump()
    restored = TranscriptMeta(**data)
    assert restored == meta


def test_meta_optional_fields():
    """META-01: All metadata fields are optional for backward compatibility."""
    meta = TranscriptMeta()
    assert meta.lead_backend is None
    assert meta.outside_backend is None
    assert meta.independence_tier is None
