"""Tests for agentcouncil.providers.openrouter — OpenRouterProvider implementation.

All tests use mocks — no real OpenRouter API required.
asyncio_mode=auto is set in pyproject.toml, so no @pytest.mark.asyncio needed.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcouncil.providers.base import ProviderError, ProviderResponse, ToolCall
from agentcouncil.providers.openrouter import OpenRouterProvider


# ---------------------------------------------------------------------------
# Helper: build a mock OpenAI SDK response
# ---------------------------------------------------------------------------


def _make_openai_response(content: str | None = None, tool_calls: list | None = None):
    """Build a mock OpenAI chat completion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call(call_id: str, name: str, arguments: dict):
    """Build a mock OpenAI tool call object (arguments is a JSON string as per SDK)."""
    fn = MagicMock()
    fn.name = name
    fn.arguments = json.dumps(arguments)  # OpenAI SDK returns arguments as JSON string
    tc = MagicMock()
    tc.id = call_id
    tc.function = fn
    return tc


# ---------------------------------------------------------------------------
# Lazy client creation — no env var required at init time
# ---------------------------------------------------------------------------


async def test_openrouter_lazy_client(monkeypatch):
    """Provider constructed without env var set does NOT raise (lazy client creation)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Should not raise even without the env var
    provider = OpenRouterProvider(model="openai/gpt-4o")
    assert provider is not None


# ---------------------------------------------------------------------------
# chat_complete — text response
# ---------------------------------------------------------------------------


async def test_openrouter_chat_complete_text_response(monkeypatch):
    """chat_complete with content response returns ProviderResponse(content=..., tool_calls=[])."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    provider = OpenRouterProvider(model="openai/gpt-4o")
    mock_response = _make_openai_response(content="hello", tool_calls=[])

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("agentcouncil.providers.openrouter.openai.AsyncOpenAI", return_value=mock_client):
        result = await provider.chat_complete([{"role": "user", "content": "hi"}])

    assert isinstance(result, ProviderResponse)
    assert result.content == "hello"
    assert result.tool_calls == []


# ---------------------------------------------------------------------------
# chat_complete — tool calls with JSON string arguments parsed to dict
# ---------------------------------------------------------------------------


async def test_openrouter_chat_complete_tool_calls(monkeypatch):
    """chat_complete with tool_calls returns ProviderResponse with ToolCall objects
    having parsed dict arguments (JSON string -> dict)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    provider = OpenRouterProvider(model="openai/gpt-4o")
    mock_tc0 = _make_tool_call("call-abc", "read_file", {"path": "foo.py"})
    mock_tc1 = _make_tool_call("call-def", "search_repo", {"query": "TODO"})
    mock_response = _make_openai_response(content=None, tool_calls=[mock_tc0, mock_tc1])

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("agentcouncil.providers.openrouter.openai.AsyncOpenAI", return_value=mock_client):
        result = await provider.chat_complete(
            [{"role": "user", "content": "do stuff"}],
            tools=[{"name": "read_file"}, {"name": "search_repo"}],
        )

    assert isinstance(result, ProviderResponse)
    assert len(result.tool_calls) == 2

    tc0 = result.tool_calls[0]
    assert tc0.id == "call-abc"
    assert tc0.name == "read_file"
    assert tc0.arguments == {"path": "foo.py"}
    assert isinstance(tc0.arguments, dict)

    tc1 = result.tool_calls[1]
    assert tc1.id == "call-def"
    assert tc1.name == "search_repo"
    assert tc1.arguments == {"query": "TODO"}


# ---------------------------------------------------------------------------
# Base URL assertion
# ---------------------------------------------------------------------------


async def test_openrouter_base_url(monkeypatch):
    """The AsyncOpenAI client is created with base_url='https://openrouter.ai/api/v1'."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    provider = OpenRouterProvider(model="openai/gpt-4o")
    mock_response = _make_openai_response(content="ok")

    captured_kwargs = {}

    def capture_client(**kwargs):
        captured_kwargs.update(kwargs)
        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        return mock_client

    with patch("agentcouncil.providers.openrouter.openai.AsyncOpenAI", side_effect=capture_client):
        await provider.chat_complete([{"role": "user", "content": "hi"}])

    assert captured_kwargs.get("base_url") == "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# auth_check — env var missing
# ---------------------------------------------------------------------------


async def test_openrouter_auth_check_no_env(monkeypatch):
    """auth_check when env var not set raises ProviderError with env var name in message."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = OpenRouterProvider(model="openai/gpt-4o")

    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        await provider.auth_check()


# ---------------------------------------------------------------------------
# auth_check — 401 response
# ---------------------------------------------------------------------------


async def test_openrouter_auth_check_401(monkeypatch):
    """auth_check when API returns 401 raises ProviderError with 'invalid' in message."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "bad-key")
    provider = OpenRouterProvider(model="openai/gpt-4o")

    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    mock_http_client.get = AsyncMock(return_value=mock_response)

    with patch("agentcouncil.providers.openrouter.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(ProviderError, match="invalid"):
            await provider.auth_check()


# ---------------------------------------------------------------------------
# auth_check — success
# ---------------------------------------------------------------------------


async def test_openrouter_auth_check_success(monkeypatch):
    """auth_check with mocked successful GET /models completes without exception."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "valid-key")
    provider = OpenRouterProvider(model="openai/gpt-4o")

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    mock_http_client.get = AsyncMock(return_value=mock_response)

    with patch("agentcouncil.providers.openrouter.httpx.AsyncClient", return_value=mock_http_client):
        await provider.auth_check()  # must not raise


# ---------------------------------------------------------------------------
# chat_complete — AuthenticationError wrapping
# ---------------------------------------------------------------------------


async def test_openrouter_chat_complete_auth_error(monkeypatch):
    """chat_complete when SDK raises AuthenticationError wraps in ProviderError."""
    import openai

    monkeypatch.setenv("OPENROUTER_API_KEY", "bad-key")
    provider = OpenRouterProvider(model="openai/gpt-4o")

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=openai.AuthenticationError(
            "invalid api key",
            response=MagicMock(status_code=401),
            body={"error": {"message": "invalid api key"}},
        )
    )

    with patch("agentcouncil.providers.openrouter.openai.AsyncOpenAI", return_value=mock_client):
        with pytest.raises(ProviderError):
            await provider.chat_complete([{"role": "user", "content": "hi"}])
