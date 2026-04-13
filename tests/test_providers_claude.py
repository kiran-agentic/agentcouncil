"""Tests for ClaudeProvider -- session-id support and capability metadata."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agentcouncil.providers.claude import ClaudeProvider
from agentcouncil.providers.base import ProviderError


# ---------------------------------------------------------------------------
# Capability attribute tests (class-level)
# ---------------------------------------------------------------------------


def test_capability_attributes():
    """ClaudeProvider declares persistent session_strategy and native workspace."""
    assert ClaudeProvider.session_strategy == "persistent"
    assert ClaudeProvider.workspace_access == "native"
    assert ClaudeProvider.supports_runtime_tools is False


# ---------------------------------------------------------------------------
# Session ID tests
# ---------------------------------------------------------------------------


def test_session_id_generated_at_init():
    """ClaudeProvider generates a UUID session_id at init time."""
    p = ClaudeProvider()
    assert p._session_id is not None
    assert len(p._session_id) == 36  # UUID format (8-4-4-4-12 with dashes)


def test_session_id_custom():
    """ClaudeProvider(session_id='custom') uses the provided session_id."""
    p = ClaudeProvider(session_id="my-session")
    assert p._session_id == "my-session"


def test_session_id_stable_across_instance():
    """Session ID is stable — same provider instance always has the same ID."""
    p = ClaudeProvider()
    sid = p._session_id
    assert p._session_id == sid  # same object, same value


def test_two_providers_have_different_session_ids():
    """Two separately constructed providers get different session IDs."""
    p1 = ClaudeProvider()
    p2 = ClaudeProvider()
    assert p1._session_id != p2._session_id


# ---------------------------------------------------------------------------
# auth_check tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_check_no_claude():
    """auth_check raises ProviderError when claude binary is not on PATH."""
    p = ClaudeProvider()
    with patch("agentcouncil.providers.claude.shutil.which", return_value=None):
        with pytest.raises(ProviderError, match="claude CLI not found"):
            await p.auth_check()


@pytest.mark.asyncio
async def test_auth_check_claude_found():
    """auth_check succeeds when claude binary is found on PATH."""
    p = ClaudeProvider()
    with patch("agentcouncil.providers.claude.shutil.which", return_value="/usr/bin/claude"):
        await p.auth_check()  # must not raise


# ---------------------------------------------------------------------------
# chat_complete tests -- session-id flag
# ---------------------------------------------------------------------------


def _make_mock_proc(returncode=0, stdout=b"response text", stderr=b""):
    """Create a mock asyncio subprocess."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return mock_proc


@pytest.mark.asyncio
async def test_chat_complete_uses_session_id():
    """chat_complete passes --session-id with the provider's session ID."""
    p = ClaudeProvider(session_id="test-sess-123")
    mock_proc = _make_mock_proc(stdout=b"response text")

    with patch(
        "agentcouncil.providers.claude.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ) as mock_exec:
        with patch(
            "agentcouncil.providers.claude.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(b"response text", b""),
        ):
            result = await p.chat_complete([{"role": "user", "content": "hello"}])

    call_args = mock_exec.call_args[0]
    assert "--session-id" in call_args
    assert "test-sess-123" in call_args
    assert "--no-session-persistence" not in call_args


@pytest.mark.asyncio
async def test_chat_complete_no_session_persistence_removed():
    """chat_complete does NOT include --no-session-persistence in the command."""
    p = ClaudeProvider()
    mock_proc = _make_mock_proc(stdout=b"ok")

    with patch(
        "agentcouncil.providers.claude.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=mock_proc,
    ) as mock_exec:
        with patch(
            "agentcouncil.providers.claude.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(b"ok", b""),
        ):
            await p.chat_complete([{"role": "user", "content": "hi"}])

    call_args = mock_exec.call_args[0]
    assert "--no-session-persistence" not in call_args


@pytest.mark.asyncio
async def test_chat_complete_two_calls_same_session_id():
    """Two chat_complete calls on the same instance use the same --session-id."""
    p = ClaudeProvider(session_id="stable-id")
    mock_proc = _make_mock_proc(stdout=b"ok")
    call_arg_lists = []

    async def capture_exec(*args, **kwargs):
        call_arg_lists.append(args)
        return mock_proc

    with patch("agentcouncil.providers.claude.asyncio.create_subprocess_exec", side_effect=capture_exec):
        with patch(
            "agentcouncil.providers.claude.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(b"ok", b""),
        ):
            await p.chat_complete([{"role": "user", "content": "first"}])
            await p.chat_complete([{"role": "user", "content": "second"}])

    assert len(call_arg_lists) == 2
    # Both calls must pass the same session-id
    assert "stable-id" in call_arg_lists[0]
    assert "stable-id" in call_arg_lists[1]
