"""Tests for agentcouncil.providers.ollama — OllamaProvider implementation.

All tests use mocks — no real Ollama instance required.
asyncio_mode=auto is set in pyproject.toml, so no @pytest.mark.asyncio needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import ollama

from agentcouncil.providers.base import ProviderError, ProviderResponse, ToolCall
from agentcouncil.providers.ollama import OllamaProvider


# ---------------------------------------------------------------------------
# Helper: build a mock chat response
# ---------------------------------------------------------------------------


def _make_chat_response(content: str | None = None, tool_calls: list | None = None):
    """Build a mock Ollama chat response object."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.message = msg
    return resp


def _make_tool_call(name: str, arguments: dict):
    """Build a mock Ollama tool call object (response.message.tool_calls[i])."""
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments
    tc = MagicMock()
    tc.function = fn
    return tc


# ---------------------------------------------------------------------------
# Default base_url test
# ---------------------------------------------------------------------------


def test_ollama_default_base_url():
    """OllamaProvider uses http://localhost:11434 as default base_url."""
    provider = OllamaProvider(model="llama3")
    assert provider._base_url == "http://localhost:11434"


# ---------------------------------------------------------------------------
# chat_complete — text response
# ---------------------------------------------------------------------------


async def test_ollama_chat_complete_text_response():
    """chat_complete with content response returns ProviderResponse(content=..., tool_calls=[])."""
    provider = OllamaProvider(model="llama3")
    mock_response = _make_chat_response(content="hello", tool_calls=[])

    with patch.object(provider._client, "chat", new=AsyncMock(return_value=mock_response)):
        result = await provider.chat_complete([{"role": "user", "content": "hi"}])

    assert isinstance(result, ProviderResponse)
    assert result.content == "hello"
    assert result.tool_calls == []


# ---------------------------------------------------------------------------
# chat_complete — tool calls with synthetic IDs
# ---------------------------------------------------------------------------


async def test_ollama_chat_complete_tool_calls():
    """chat_complete with tool_calls returns ProviderResponse with synthetic IDs ollama-0, ollama-1."""
    provider = OllamaProvider(model="llama3")
    mock_tc0 = _make_tool_call("read_file", {"path": "foo.py"})
    mock_tc1 = _make_tool_call("search_repo", {"query": "TODO"})
    mock_response = _make_chat_response(content=None, tool_calls=[mock_tc0, mock_tc1])

    with patch.object(provider._client, "chat", new=AsyncMock(return_value=mock_response)):
        result = await provider.chat_complete(
            [{"role": "user", "content": "do stuff"}],
            tools=[{"name": "read_file"}, {"name": "search_repo"}],
        )

    assert isinstance(result, ProviderResponse)
    assert len(result.tool_calls) == 2

    tc0 = result.tool_calls[0]
    assert tc0.id == "ollama-0"
    assert tc0.name == "read_file"
    assert tc0.arguments == {"path": "foo.py"}

    tc1 = result.tool_calls[1]
    assert tc1.id == "ollama-1"
    assert tc1.name == "search_repo"
    assert tc1.arguments == {"query": "TODO"}


# ---------------------------------------------------------------------------
# chat_complete — stream=False is always passed
# ---------------------------------------------------------------------------


async def test_ollama_uses_stream_false():
    """chat_complete passes stream=False to the SDK chat() method."""
    provider = OllamaProvider(model="llama3")
    mock_response = _make_chat_response(content="ok")
    mock_chat = AsyncMock(return_value=mock_response)

    with patch.object(provider._client, "chat", new=mock_chat):
        await provider.chat_complete([{"role": "user", "content": "hi"}])

    mock_chat.assert_called_once()
    _, kwargs = mock_chat.call_args
    assert kwargs.get("stream") is False


# ---------------------------------------------------------------------------
# auth_check — success
# ---------------------------------------------------------------------------


async def test_ollama_auth_check_success():
    """auth_check with mocked client.list() succeeding completes without exception."""
    provider = OllamaProvider(model="llama3")

    with patch.object(provider._client, "list", new=AsyncMock(return_value=MagicMock())):
        await provider.auth_check()  # must not raise


# ---------------------------------------------------------------------------
# auth_check — failure
# ---------------------------------------------------------------------------


async def test_ollama_auth_check_failure():
    """auth_check with client.list() raising wraps in ProviderError with 'not reachable'."""
    provider = OllamaProvider(model="llama3")

    with patch.object(
        provider._client,
        "list",
        new=AsyncMock(side_effect=Exception("connection refused")),
    ):
        with pytest.raises(ProviderError, match="not reachable"):
            await provider.auth_check()


# ---------------------------------------------------------------------------
# chat_complete — SDK error wrapping
# ---------------------------------------------------------------------------


async def test_ollama_chat_complete_sdk_error():
    """chat_complete when SDK raises ollama.ResponseError wraps in ProviderError."""
    provider = OllamaProvider(model="llama3")

    with patch.object(
        provider._client,
        "chat",
        new=AsyncMock(side_effect=ollama.ResponseError("model not found")),
    ):
        with pytest.raises(ProviderError):
            await provider.chat_complete([{"role": "user", "content": "hi"}])
