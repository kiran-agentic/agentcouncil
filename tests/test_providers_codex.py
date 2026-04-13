"""Tests for CodexProvider -- capability metadata, auth, lifecycle, and MCP session."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentcouncil.providers.codex import CodexProvider
from agentcouncil.providers.base import ProviderError, ProviderResponse


# ---------------------------------------------------------------------------
# Capability attribute tests (class-level)
# ---------------------------------------------------------------------------


def test_capability_attributes():
    """CodexProvider declares persistent session_strategy and native workspace."""
    assert CodexProvider.session_strategy == "persistent"
    assert CodexProvider.workspace_access == "native"
    assert CodexProvider.supports_runtime_tools is False


# ---------------------------------------------------------------------------
# auth_check tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_check_no_codex():
    """auth_check raises ProviderError when codex binary is not on PATH."""
    p = CodexProvider()
    with patch("agentcouncil.providers.codex.shutil.which", return_value=None):
        with pytest.raises(ProviderError, match="codex CLI not found"):
            await p.auth_check()


@pytest.mark.asyncio
async def test_auth_check_codex_found():
    """auth_check succeeds when codex binary is found on PATH."""
    p = CodexProvider()
    with patch("agentcouncil.providers.codex.shutil.which", return_value="/usr/bin/codex"):
        await p.auth_check()  # must not raise


# ---------------------------------------------------------------------------
# close() idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_idempotent():
    """Calling close() twice must not raise."""
    p = CodexProvider()
    await p.close()  # first call on unstarted provider — should no-op
    await p.close()  # second call — also no-op


@pytest.mark.asyncio
async def test_close_clears_state():
    """After close(), _client and _thread_id are set to None."""
    p = CodexProvider()
    # Simulate a started state
    mock_client = MagicMock()
    mock_client.__aexit__ = AsyncMock(return_value=None)
    p._client = mock_client
    p._thread_id = "some-thread-id"

    await p.close()

    assert p._client is None
    assert p._thread_id is None


# ---------------------------------------------------------------------------
# chat_complete tests
# ---------------------------------------------------------------------------


def _make_mock_result(thread_id="thread-abc", text="response text"):
    """Create a mock MCP call result with structured_content and content list."""
    result = MagicMock()
    result.structured_content = {"threadId": thread_id}
    # Ensure text attribute is falsy so _extract_text falls through to content list
    result.text = None
    content_item = MagicMock()
    content_item.text = text
    result.content = [content_item]
    return result


@pytest.mark.asyncio
async def test_chat_complete_first_call():
    """First chat_complete call uses 'codex' tool with prompt and sandbox."""
    p = CodexProvider(sandbox="read-only")
    mock_result = _make_mock_result(thread_id="thread-xyz", text="first response")

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.call_tool = AsyncMock(return_value=mock_result)

    # Client is imported inside _start() — patch via fastmcp module
    with patch("fastmcp.Client", return_value=mock_client):
        result = await p.chat_complete([{"role": "user", "content": "hello codex"}])

    # Verify first call uses "codex" tool
    mock_client.call_tool.assert_called_once()
    call_args = mock_client.call_tool.call_args
    assert call_args[0][0] == "codex"
    assert call_args[0][1]["prompt"] == "hello codex"
    assert call_args[0][1]["sandbox"] == "read-only"

    assert isinstance(result, ProviderResponse)
    assert result.content == "first response"


@pytest.mark.asyncio
async def test_chat_complete_reply():
    """Second chat_complete call uses 'codex-reply' tool with threadId."""
    p = CodexProvider()
    first_result = _make_mock_result(thread_id="thread-123", text="first")
    second_result = MagicMock()
    second_result.text = None
    second_item = MagicMock()
    second_item.text = "second"
    second_result.content = [second_item]

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.call_tool = AsyncMock(side_effect=[first_result, second_result])

    with patch("fastmcp.Client", return_value=mock_client):
        await p.chat_complete([{"role": "user", "content": "first question"}])
        await p.chat_complete([{"role": "user", "content": "follow up"}])

    # Second call should use codex-reply with the threadId from first call
    assert mock_client.call_tool.call_count == 2
    second_call = mock_client.call_tool.call_args_list[1]
    assert second_call[0][0] == "codex-reply"
    assert second_call[0][1]["threadId"] == "thread-123"
    assert second_call[0][1]["prompt"] == "follow up"
