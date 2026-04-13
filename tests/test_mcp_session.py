"""Tests for MCP session tools in agentcouncil.server.

Covers all 4 new MCP session tools:
    - outside_start_tool
    - outside_reply_tool
    - outside_close_tool
    - get_outside_backend_info_tool

Covers skill migration tests (Plan 02):
    - test_skill_backend_param
    - test_skill_legacy_fallback
    - test_skill_workspace_access_flag
    - test_brainstorm_is_async

Uses StubProvider + monkeypatching to avoid real provider dependencies.
"""
from __future__ import annotations

import asyncio
import json
import warnings
import uuid

import pytest
import pytest_asyncio

# Suppress DeprecationWarning from AgentAdapter at import time
warnings.filterwarnings("ignore", category=DeprecationWarning, module="agentcouncil.session")

from agentcouncil.server import (  # noqa: E402
    mcp,
    _SESSIONS,
    _make_provider,
    outside_start_tool,
    outside_reply_tool,
    outside_close_tool,
    outside_query_tool,
    get_outside_backend_info_tool,
    brainstorm_tool,
    review_tool,
    decide_tool,
    challenge_tool,
)
from agentcouncil.adapters import StubAdapter
from agentcouncil.providers.base import ProviderResponse, StubProvider, ProviderError
from agentcouncil.config import BackendProfile, ProfileLoader
from agentcouncil.session import OutsideSession


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_provider(monkeypatch):
    """Monkeypatch _make_provider and OutsideRuntime.run_turn for unit tests.

    - _make_provider returns a StubProvider cycling "stub response"
    - OutsideRuntime.run_turn is patched to return "stub response" directly
    - _SESSIONS is cleared before and after each test
    """
    _SESSIONS.clear()

    stub = StubProvider(ProviderResponse(content="stub response"))

    monkeypatch.setattr("agentcouncil.server._make_provider", lambda *a, **kw: stub)

    # Patch OutsideRuntime.run_turn so we don't execute the real tool loop
    async def _fake_run_turn(self, messages):
        return "stub response"

    monkeypatch.setattr("agentcouncil.runtime.OutsideRuntime.run_turn", _fake_run_turn)

    yield stub

    _SESSIONS.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outside_start_returns_session_id(patch_provider):
    """outside_start returns a dict with valid session_id and response."""
    result = await outside_start_tool(prompt="hello", profile="test")

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "session_id" in result, f"Missing 'session_id' key: {result}"
    assert "response" in result, f"Missing 'response' key: {result}"

    # Validate UUID format
    parsed = uuid.UUID(result["session_id"])
    assert str(parsed) == result["session_id"]

    assert result["response"] == "stub response"
    assert result["session_id"] in _SESSIONS


@pytest.mark.asyncio
async def test_outside_reply_continues_session(patch_provider):
    """outside_reply continues an existing session and returns a response."""
    start_result = await outside_start_tool(prompt="hello", profile="test")
    reply_result = await outside_reply_tool(session_id=start_result["session_id"], prompt="more")

    assert isinstance(reply_result, dict)
    assert reply_result["response"] == "stub response"


@pytest.mark.asyncio
async def test_outside_reply_unknown_session(patch_provider):
    """outside_reply raises ValueError on unknown session_id."""
    with pytest.raises(ValueError, match="Unknown session_id"):
        await outside_reply_tool(session_id="bogus-id", prompt="x")


@pytest.mark.asyncio
async def test_outside_close_cleans_up(patch_provider):
    """outside_close returns status=closed and removes session from registry."""
    start_result = await outside_start_tool(prompt="hello", profile="test")
    sid = start_result["session_id"]
    assert sid in _SESSIONS

    close_result = await outside_close_tool(session_id=sid)

    assert close_result["status"] == "closed"
    assert close_result["session_id"] == sid
    assert sid not in _SESSIONS


@pytest.mark.asyncio
async def test_outside_close_unknown_session(patch_provider):
    """outside_close raises ValueError on unknown session_id."""
    with pytest.raises(ValueError, match="Unknown session_id"):
        await outside_close_tool(session_id="bogus-id")


def test_get_outside_backend_info_returns_caps(monkeypatch):
    """get_outside_backend_info returns correct capability dict for BackendProfile."""
    monkeypatch.setattr(
        ProfileLoader,
        "resolve",
        lambda self, profile_name=None, skill_backend=None: BackendProfile(
            provider="ollama", model="llama3"
        ),
    )
    result = get_outside_backend_info_tool(profile="test")

    assert result == {
        "provider": "ollama",
        "model": "llama3",
        "workspace_access": "assisted",
        "session_strategy": "replay",
        "supports_runtime_tools": True,
    }


def test_get_outside_backend_info_legacy_backend(monkeypatch):
    """get_outside_backend_info handles legacy string return from ProfileLoader.

    When resolve returns 'codex', _make_provider now dispatches to CodexProvider
    (UPROV-03), so the result reflects CodexProvider's capability attrs.
    Mock shutil.which so the binary guard passes in CI.
    """
    monkeypatch.setattr(
        ProfileLoader,
        "resolve",
        lambda self, profile_name=None, skill_backend=None: "codex",
    )
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    result = get_outside_backend_info_tool()

    assert result["provider"] == "codex"
    assert result["workspace_access"] == "native"
    assert result["supports_runtime_tools"] is False


@pytest.mark.asyncio
async def test_full_session_lifecycle(patch_provider):
    """Full lifecycle: start -> reply -> reply -> close all succeed."""
    start = await outside_start_tool(prompt="hello", profile="test")
    sid = start["session_id"]

    r1 = await outside_reply_tool(session_id=sid, prompt="second")
    r2 = await outside_reply_tool(session_id=sid, prompt="third")
    close = await outside_close_tool(session_id=sid)

    assert start["response"] == "stub response"
    assert r1["response"] == "stub response"
    assert r2["response"] == "stub response"
    assert close["status"] == "closed"
    assert sid not in _SESSIONS


@pytest.mark.asyncio
async def test_get_outside_backend_info_no_session_opened(monkeypatch):
    """get_outside_backend_info does not create a session or call auth_check."""
    monkeypatch.setattr(
        ProfileLoader,
        "resolve",
        lambda self, profile_name=None, skill_backend=None: BackendProfile(
            provider="ollama", model="llama3"
        ),
    )

    # Ensure _SESSIONS is empty before and after
    _SESSIONS.clear()
    result = get_outside_backend_info_tool(profile="test")

    assert "provider" in result
    assert len(_SESSIONS) == 0, "get_outside_backend_info must not open a session"


# ---------------------------------------------------------------------------
# Skill migration tests (Plan 02: SKIL-01, SKIL-02, SKIL-03)
# ---------------------------------------------------------------------------

# Valid ReviewArtifact JSON for synthesis stub response
_STUB_REVIEW_ARTIFACT_JSON = json.dumps({
    "verdict": "pass",
    "summary": "stub review",
    "findings": [],
    "strengths": ["ok"],
    "open_questions": [],
    "next_action": "ship it",
})


@pytest.fixture
def patch_skill_provider(monkeypatch):
    """Monkeypatch _make_provider + OutsideRuntime.run_turn for skill tool tests.

    Also patches ClaudeAdapter to return stub responses so no real CLI is needed.
    """
    stub = StubProvider(ProviderResponse(content="stub outside response"))
    monkeypatch.setattr("agentcouncil.server._make_provider", lambda *a, **kw: stub)

    # Stub out OutsideRuntime.run_turn — returns the review artifact JSON on synthesis
    call_count = [0]

    async def _fake_run_turn(self, messages):
        call_count[0] += 1
        # First call: outside initial analysis (free text)
        # Second call (if exchanges): exchange
        # Last call: synthesis — return valid artifact JSON
        return _STUB_REVIEW_ARTIFACT_JSON if call_count[0] > 1 else "stub initial analysis"

    monkeypatch.setattr("agentcouncil.runtime.OutsideRuntime.run_turn", _fake_run_turn)

    # Stub ClaudeAdapter — lead agent returns a simple text response first, then JSON
    lead_responses = ["lead initial analysis", _STUB_REVIEW_ARTIFACT_JSON]

    class StubClaudeAdapter:
        def __init__(self, *args, **kwargs):
            self._idx = 0

        def call(self, prompt):
            resp = lead_responses[min(self._idx, len(lead_responses) - 1)]
            self._idx += 1
            return resp

        async def acall(self, prompt):
            return self.call(prompt)

    monkeypatch.setattr("agentcouncil.server.ClaudeAdapter", StubClaudeAdapter)

    yield stub


@pytest.mark.asyncio
async def test_skill_backend_param(patch_skill_provider, monkeypatch):
    """SKIL-01: review_tool accepts backend= kwarg and uses OutsideSession path."""
    # Track whether OutsideSession was instantiated
    session_instances = []
    original_init = OutsideSession.__init__

    def tracking_init(self, *args, **kwargs):
        session_instances.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(OutsideSession, "__init__", tracking_init)

    # Should not raise; backend= param is accepted
    result = await review_tool(artifact="test artifact", backend="test-profile")

    assert isinstance(result, dict)
    assert "artifact" in result
    # Verify it went through OutsideSession path (not legacy path)
    assert len(session_instances) > 0, "Expected OutsideSession to be created for named profile"


@pytest.mark.asyncio
async def test_skill_legacy_fallback(monkeypatch):
    """SKIL-02: review_tool falls back to legacy adapter path for legacy backend strings."""
    # Patch _make_provider to raise ValueError so the legacy fallback path is exercised.
    # In production this happens for unrecognized backend strings.
    monkeypatch.setattr("agentcouncil.server._make_provider", lambda **kw: (_ for _ in ()).throw(ValueError("test")))

    # We need a stub that returns valid review artifact JSON on synthesis
    stub_responses = ["outside initial", _STUB_REVIEW_ARTIFACT_JSON]
    stub_outside = StubAdapter(stub_responses)
    stub_lead = StubAdapter(["lead initial"])

    monkeypatch.setattr("agentcouncil.server.resolve_outside_adapter", lambda *a, **kw: stub_outside)
    monkeypatch.setattr("agentcouncil.server.resolve_outside_backend", lambda b: "codex")

    # Also stub ClaudeAdapter (lead agent)
    class StubClaudeAdapter:
        def __init__(self, *a, **kw):
            pass

        def call(self, prompt):
            return "lead initial analysis"

        async def acall(self, prompt):
            return self.call(prompt)

    monkeypatch.setattr("agentcouncil.server.ClaudeAdapter", StubClaudeAdapter)

    # Should succeed via legacy fallback
    result = await review_tool(artifact="test", backend="codex")

    assert isinstance(result, dict), f"Expected dict result, got {type(result)}: {result}"


@pytest.mark.asyncio
async def test_skill_workspace_access_flag(monkeypatch):
    """SKIL-03: OutsideSession.workspace_access is 'assisted' for provider-backed sessions."""
    stub = StubProvider(ProviderResponse(content=_STUB_REVIEW_ARTIFACT_JSON))
    monkeypatch.setattr("agentcouncil.server._make_provider", lambda *a, **kw: stub)

    captured_sessions = []
    original_init = OutsideSession.__init__

    def tracking_init(self, *args, **kwargs):
        captured_sessions.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(OutsideSession, "__init__", tracking_init)

    async def _fake_run_turn(self, messages):
        return _STUB_REVIEW_ARTIFACT_JSON

    monkeypatch.setattr("agentcouncil.runtime.OutsideRuntime.run_turn", _fake_run_turn)

    class StubClaudeAdapter:
        def __init__(self, *a, **kw):
            pass

        async def acall(self, prompt):
            return "lead analysis"

        def call(self, prompt):
            return "lead analysis"

    monkeypatch.setattr("agentcouncil.server.ClaudeAdapter", StubClaudeAdapter)

    await review_tool(artifact="test", backend="test-profile")

    assert len(captured_sessions) > 0, "Expected OutsideSession to be captured"
    session = captured_sessions[0]
    assert session.workspace_access == "assisted", (
        f"Expected workspace_access='assisted', got {session.workspace_access!r}"
    )


def test_brainstorm_is_async():
    """SKIL-01: brainstorm_tool is a coroutine function (async def)."""
    assert asyncio.iscoroutinefunction(brainstorm_tool), (
        "brainstorm_tool must be async — it was converted in Plan 02"
    )


# ---------------------------------------------------------------------------
# UPROV-03 dispatch tests (Plan 02)
# ---------------------------------------------------------------------------


def test_make_provider_codex_from_string(monkeypatch):
    """_make_provider('codex') returns CodexProvider when resolve returns 'codex' string."""
    from agentcouncil.providers.codex import CodexProvider
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "codex",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}")
    provider = _make_provider("codex")
    assert isinstance(provider, CodexProvider)


def test_make_provider_claude_from_string(monkeypatch):
    """_make_provider('claude') returns ClaudeProvider when resolve returns 'claude' string."""
    from agentcouncil.providers.claude import ClaudeProvider
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "claude",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}")
    provider = _make_provider("claude")
    assert isinstance(provider, ClaudeProvider)


def test_make_provider_codex_from_profile(monkeypatch):
    """_make_provider with BackendProfile(provider='codex') returns CodexProvider."""
    from agentcouncil.providers.codex import CodexProvider
    bp = BackendProfile(provider="codex", model="o4-mini")
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: bp,
    )
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}")
    provider = _make_provider("my-codex-profile", model=None)
    assert isinstance(provider, CodexProvider)
    assert provider._model == "o4-mini"


def test_make_provider_claude_from_profile(monkeypatch):
    """_make_provider with BackendProfile(provider='claude') returns ClaudeProvider."""
    from agentcouncil.providers.claude import ClaudeProvider
    bp = BackendProfile(provider="claude", model="sonnet")
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: bp,
    )
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}")
    provider = _make_provider("my-claude-profile", model=None)
    assert isinstance(provider, ClaudeProvider)
    assert provider._model == "sonnet"


def test_make_provider_unknown_string_still_raises(monkeypatch):
    """_make_provider('unknown') still raises ValueError for unrecognized legacy strings."""
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "unknown-backend",
    )
    with pytest.raises(ValueError, match="Session API requires a named profile"):
        _make_provider("unknown-backend")


def test_make_provider_default_is_claude(monkeypatch):
    """UFALL-01: _make_provider(None) defaults to ClaudeProvider when no config."""
    from agentcouncil.providers.claude import ClaudeProvider
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/claude" if cmd == "claude" else None)
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "claude",
    )
    provider = _make_provider(None)
    assert isinstance(provider, ClaudeProvider)


def test_make_provider_codex_binary_missing_string(monkeypatch):
    """UFALL-02: _make_provider('codex') raises ProviderError when codex binary absent."""
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "codex",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    with pytest.raises(ProviderError, match="codex binary not found"):
        _make_provider("codex")


def test_make_provider_claude_binary_missing_string(monkeypatch):
    """UFALL-02: _make_provider('claude') raises ProviderError when claude binary absent."""
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "claude",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    with pytest.raises(ProviderError, match="claude binary not found"):
        _make_provider("claude")


def test_make_provider_codex_binary_missing_profile(monkeypatch):
    """UFALL-02: _make_provider with BackendProfile(provider='codex') raises ProviderError when binary absent."""
    bp = BackendProfile(provider="codex", model="o4-mini")
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: bp,
    )
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    with pytest.raises(ProviderError, match="codex binary not found"):
        _make_provider("my-codex-profile")


def test_make_provider_claude_binary_missing_profile(monkeypatch):
    """UFALL-02: _make_provider with BackendProfile(provider='claude') raises ProviderError when binary absent."""
    bp = BackendProfile(provider="claude", model="sonnet")
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: bp,
    )
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    with pytest.raises(ProviderError, match="claude binary not found"):
        _make_provider("my-claude-profile")


def test_make_provider_codex_binary_present(monkeypatch):
    """UFALL-02: _make_provider('codex') succeeds when codex binary is present."""
    from agentcouncil.providers.codex import CodexProvider
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "codex",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/codex" if cmd == "codex" else None)
    provider = _make_provider("codex")
    assert isinstance(provider, CodexProvider)


def test_make_provider_claude_binary_present(monkeypatch):
    """UFALL-02: _make_provider('claude') succeeds when claude binary is present."""
    from agentcouncil.providers.claude import ClaudeProvider
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "claude",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/claude" if cmd == "claude" else None)
    provider = _make_provider("claude")
    assert isinstance(provider, ClaudeProvider)


def test_get_backend_info_returns_capability_keys(monkeypatch):
    """get_outside_backend_info_tool returns session_strategy, workspace_access, supports_runtime_tools."""
    monkeypatch.setattr(
        "agentcouncil.server.ProfileLoader.resolve",
        lambda self, profile_name=None: "codex",
    )
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}")
    info = get_outside_backend_info_tool(profile="codex")
    assert info["session_strategy"] == "persistent"
    assert info["workspace_access"] == "native"
    assert info["supports_runtime_tools"] is False
    assert "provider" in info


# ---------------------------------------------------------------------------
# UCOMPAT-01: outside_query shim tests (Plan 24-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outside_query_deprecation_notice(patch_provider):
    """UCOMPAT-01: outside_query response includes deprecation notice."""
    result = await outside_query_tool("test prompt")
    assert "DEPRECATED: outside_query is deprecated" in result
    assert "outside_start/outside_reply/outside_close" in result


@pytest.mark.asyncio
async def test_outside_query_returns_response(patch_provider):
    """UCOMPAT-01: outside_query returns the provider response content."""
    result = await outside_query_tool("test prompt")
    assert "stub response" in result


@pytest.mark.asyncio
async def test_outside_query_uses_provider_pipeline(monkeypatch):
    """UCOMPAT-01: outside_query routes through _make_provider, not legacy adapter."""
    from agentcouncil.providers.base import ProviderResponse, StubProvider

    stub = StubProvider(ProviderResponse(content="pipeline response"))
    called_with = {}

    def capture_make_provider(*args, **kwargs):
        called_with["args"] = args
        called_with["kwargs"] = kwargs
        return stub

    async def _fake_run_turn(self, messages):
        return "pipeline response"

    monkeypatch.setattr("agentcouncil.server._make_provider", capture_make_provider)
    monkeypatch.setattr("agentcouncil.runtime.OutsideRuntime.run_turn", _fake_run_turn)
    monkeypatch.setattr("agentcouncil.server._SESSIONS", {})

    result = await outside_query_tool("test prompt", outside_agent="my-profile")
    assert "pipeline response" in result
    assert called_with  # _make_provider was called


@pytest.mark.asyncio
async def test_outside_query_legacy_fallback(monkeypatch):
    """UCOMPAT-01: outside_query falls back to legacy adapter on ValueError."""

    def raise_value_error(*args, **kwargs):
        raise ValueError("legacy backend")

    monkeypatch.setattr("agentcouncil.server._make_provider", raise_value_error)
    monkeypatch.setattr(
        "agentcouncil.server.resolve_outside_adapter",
        lambda backend=None, timeout=300: type(
            "FakeAdapter", (), {"call": lambda self, p: "legacy response"}
        )(),
    )

    result = await outside_query_tool("test prompt")
    assert "legacy response" in result
    assert "DEPRECATED" in result
