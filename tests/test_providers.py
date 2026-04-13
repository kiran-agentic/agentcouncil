"""Tests for agentcouncil.providers — OutsideProvider ABC, response models, StubProvider."""
from __future__ import annotations

import pytest

from agentcouncil.providers import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
    StubProvider,
    ToolCall,
)


# ---------------------------------------------------------------------------
# OutsideProvider ABC tests
# ---------------------------------------------------------------------------


def test_outside_provider_cannot_be_instantiated() -> None:
    """OutsideProvider is abstract — direct instantiation raises TypeError."""
    with pytest.raises(TypeError):
        OutsideProvider()  # type: ignore[abstract]


def test_subclass_missing_chat_complete_raises_on_instantiation() -> None:
    """A subclass that omits chat_complete raises TypeError."""

    class BadProvider(OutsideProvider):  # type: ignore[misc]
        async def auth_check(self) -> None:
            pass

    with pytest.raises(TypeError):
        BadProvider()


def test_subclass_missing_auth_check_raises_on_instantiation() -> None:
    """A subclass that omits auth_check raises TypeError."""

    class BadProvider(OutsideProvider):  # type: ignore[misc]
        async def chat_complete(self, messages, tools=None):  # type: ignore[override]
            return ProviderResponse(content="ok")

    with pytest.raises(TypeError):
        BadProvider()


# ---------------------------------------------------------------------------
# ProviderResponse model tests
# ---------------------------------------------------------------------------


def test_provider_response_defaults() -> None:
    """ProviderResponse with content has content and empty tool_calls."""
    resp = ProviderResponse(content="hello")
    assert resp.content == "hello"
    assert resp.tool_calls == []


def test_provider_response_with_tool_calls() -> None:
    """ProviderResponse accepts tool_calls with ToolCall objects."""
    tc = ToolCall(id="1", name="read_file", arguments={"path": "x.py"})
    resp = ProviderResponse(content=None, tool_calls=[tc])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].arguments == {"path": "x.py"}


# ---------------------------------------------------------------------------
# ToolCall model tests
# ---------------------------------------------------------------------------


def test_tool_call_fields() -> None:
    """ToolCall validates id, name, arguments fields."""
    tc = ToolCall(id="tc-1", name="search_repo", arguments={"query": "TODO"})
    assert tc.id == "tc-1"
    assert tc.name == "search_repo"
    assert tc.arguments == {"query": "TODO"}


# ---------------------------------------------------------------------------
# ProviderError tests
# ---------------------------------------------------------------------------


def test_provider_error_is_exception() -> None:
    """ProviderError is an Exception subclass with a message."""
    err = ProviderError("something went wrong")
    assert isinstance(err, Exception)
    assert str(err) == "something went wrong"


# ---------------------------------------------------------------------------
# StubProvider behavioral tests
# ---------------------------------------------------------------------------


async def test_stub_provider_returns_configured_response() -> None:
    """StubProvider.chat_complete returns the configured ProviderResponse."""
    stub = StubProvider(ProviderResponse(content="hi"))
    result = await stub.chat_complete([{"role": "user", "content": "hello"}])
    assert isinstance(result, ProviderResponse)
    assert result.content == "hi"


async def test_stub_provider_list_returns_in_order() -> None:
    """StubProvider with list pops responses in order."""
    responses = [
        ProviderResponse(content="first"),
        ProviderResponse(content="second"),
    ]
    stub = StubProvider(responses)
    r1 = await stub.chat_complete([{"role": "user", "content": "q1"}])
    r2 = await stub.chat_complete([{"role": "user", "content": "q2"}])
    assert r1.content == "first"
    assert r2.content == "second"


async def test_stub_provider_list_raises_on_exhaustion() -> None:
    """StubProvider with exhausted list raises ProviderError."""
    stub = StubProvider([ProviderResponse(content="only")])
    await stub.chat_complete([{"role": "user", "content": "q1"}])
    with pytest.raises(ProviderError, match="exhausted"):
        await stub.chat_complete([{"role": "user", "content": "q2"}])


async def test_stub_provider_single_cycles_indefinitely() -> None:
    """StubProvider with single response cycles indefinitely."""
    stub = StubProvider(ProviderResponse(content="repeat"))
    for _ in range(5):
        r = await stub.chat_complete([{"role": "user", "content": "q"}])
        assert r.content == "repeat"


async def test_stub_provider_auth_check_passes() -> None:
    """StubProvider.auth_check() completes without raising."""
    stub = StubProvider(ProviderResponse(content="ok"))
    await stub.auth_check()  # must not raise


async def test_stub_provider_records_calls() -> None:
    """StubProvider.calls records each messages list passed to chat_complete."""
    stub = StubProvider(ProviderResponse(content="ok"))
    msgs1 = [{"role": "user", "content": "first"}]
    msgs2 = [{"role": "user", "content": "second"}]
    await stub.chat_complete(msgs1)
    await stub.chat_complete(msgs2)
    assert len(stub.calls) == 2
    assert stub.calls[0] == msgs1
    assert stub.calls[1] == msgs2


# ---------------------------------------------------------------------------
# OutsideProvider capability attribute defaults (UPROV-04)
# ---------------------------------------------------------------------------


def test_outside_provider_default_session_strategy() -> None:
    """OutsideProvider default session_strategy is 'replay' (class-level)."""
    assert OutsideProvider.session_strategy == "replay"


def test_outside_provider_default_workspace_access() -> None:
    """OutsideProvider default workspace_access is 'assisted' (class-level)."""
    assert OutsideProvider.workspace_access == "assisted"


def test_outside_provider_default_supports_runtime_tools() -> None:
    """OutsideProvider default supports_runtime_tools is True (class-level)."""
    assert OutsideProvider.supports_runtime_tools is True


def test_stub_provider_inherits_default_session_strategy() -> None:
    """StubProvider inherits session_strategy='replay' from OutsideProvider."""
    assert StubProvider.session_strategy == "replay"


def test_stub_provider_inherits_default_workspace_access() -> None:
    """StubProvider inherits workspace_access='assisted' from OutsideProvider."""
    assert StubProvider.workspace_access == "assisted"


def test_stub_provider_inherits_default_supports_runtime_tools() -> None:
    """StubProvider inherits supports_runtime_tools=True from OutsideProvider."""
    assert StubProvider.supports_runtime_tools is True


# ---------------------------------------------------------------------------
# pyproject.toml optional extras test (Task 2 — appended below)
# ---------------------------------------------------------------------------


def test_pyproject_optional_extras_declared() -> None:
    """pyproject.toml declares ollama, openrouter, and bedrock optional extras."""
    import tomllib
    from pathlib import Path

    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    optional_deps = data.get("project", {}).get("optional-dependencies", {})
    assert "ollama" in optional_deps, "ollama extra missing from pyproject.toml"
    assert "openrouter" in optional_deps, "openrouter extra missing from pyproject.toml"
    assert "bedrock" in optional_deps, "bedrock extra missing from pyproject.toml"
