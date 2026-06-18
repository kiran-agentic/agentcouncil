"""Tests for CursorProvider — cursor-agent CLI subprocess, JSON parse, replay history."""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentcouncil.providers.base import ProviderError
from agentcouncil.providers.cursor import CursorProvider


# ---------------------------------------------------------------------------
# Capability attributes
# ---------------------------------------------------------------------------


def test_capability_attributes():
    """CursorProvider is a stateless (replay) native-workspace provider."""
    assert CursorProvider.session_strategy == "replay"
    assert CursorProvider.workspace_access == "native"
    assert CursorProvider.supports_runtime_tools is False


# ---------------------------------------------------------------------------
# auth_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_check_missing_binary():
    p = CursorProvider()
    with patch("agentcouncil.providers.cursor.shutil.which", return_value=None):
        with pytest.raises(ProviderError, match="cursor-agent CLI not found"):
            await p.auth_check()


@pytest.mark.asyncio
async def test_auth_check_binary_found():
    p = CursorProvider()
    with patch(
        "agentcouncil.providers.cursor.shutil.which",
        return_value="/usr/bin/cursor-agent",
    ):
        await p.auth_check()  # must not raise


# ---------------------------------------------------------------------------
# chat_complete helpers
# ---------------------------------------------------------------------------


def _mock_proc(returncode=0):
    proc = MagicMock()
    proc.returncode = returncode
    # communicate() is invoked as the argument to the patched asyncio.wait_for and
    # never actually awaited, so a plain MagicMock (not AsyncMock) avoids a
    # "coroutine was never awaited" warning.
    proc.communicate = MagicMock(return_value=(b"", b""))
    return proc


def _json_out(result="hello", is_error=False, subtype="success"):
    return json.dumps(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "result": result,
            "session_id": "sess-1",
        }
    ).encode()


# ---------------------------------------------------------------------------
# chat_complete — command construction, JSON parsing, model flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_complete_builds_command_and_parses_result():
    p = CursorProvider(model="gpt-5")
    proc = _mock_proc()
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ) as mock_exec:
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(_json_out("the answer"), b""),
        ):
            resp = await p.chat_complete([{"role": "user", "content": "hi there"}])

    assert resp.content == "the answer"
    args = mock_exec.call_args[0]
    assert "cursor-agent" in args
    assert "--print" in args
    assert "--output-format" in args and "json" in args
    assert "--model" in args and "gpt-5" in args
    assert "--resume" not in args  # replay strategy never resumes
    assert args[-1] == "hi there"  # lone user message sent verbatim


@pytest.mark.asyncio
async def test_chat_complete_no_model_flag_when_unset():
    p = CursorProvider()
    proc = _mock_proc()
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ) as mock_exec:
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(_json_out(), b""),
        ):
            await p.chat_complete([{"role": "user", "content": "hi"}])
    assert "--model" not in mock_exec.call_args[0]


@pytest.mark.asyncio
async def test_chat_complete_replays_full_history():
    """Replay strategy: the full conversation is serialized into the prompt each turn."""
    p = CursorProvider()
    proc = _mock_proc()
    captured = []

    async def capture(*args, **kwargs):
        captured.append(args)
        return proc

    outputs = [(_json_out("a1"), b""), (_json_out("a2"), b"")]
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        side_effect=capture,
    ):
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            side_effect=outputs,
        ):
            await p.chat_complete([{"role": "user", "content": "first question"}])
            await p.chat_complete(
                [
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "first answer"},
                    {"role": "user", "content": "second question"},
                ]
            )

    # First call: lone user message verbatim.
    assert captured[0][-1] == "first question"
    # Second call: full transcript, role-labelled, no --resume.
    prompt2 = captured[1][-1]
    assert "first question" in prompt2
    assert "first answer" in prompt2
    assert "second question" in prompt2
    assert "USER:" in prompt2 and "ASSISTANT:" in prompt2
    assert "--resume" not in captured[0]
    assert "--resume" not in captured[1]


# ---------------------------------------------------------------------------
# chat_complete — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_complete_in_band_error_raises():
    """Exit 0 but is_error:true in the JSON envelope must raise, not return content."""
    p = CursorProvider()
    proc = _mock_proc(returncode=0)
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ):
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(_json_out("boom", is_error=True, subtype="error"), b""),
        ):
            with pytest.raises(ProviderError, match="reported an error"):
                await p.chat_complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_complete_nonzero_exit_raises():
    p = CursorProvider()
    proc = _mock_proc(returncode=2)
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ):
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(b"", b"boom"),
        ):
            with pytest.raises(ProviderError, match="cursor-agent failed"):
                await p.chat_complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_complete_timeout_raises():
    import asyncio

    p = CursorProvider(timeout=0.01)
    proc = _mock_proc()
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ):
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError(),
        ):
            with pytest.raises(ProviderError, match="timed out"):
                await p.chat_complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_complete_falls_back_on_non_json():
    """If stdout isn't JSON, the raw text is used (defensive)."""
    p = CursorProvider()
    proc = _mock_proc()
    with patch(
        "agentcouncil.providers.cursor.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ):
        with patch(
            "agentcouncil.providers.cursor.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=(b"plain text answer", b""),
        ):
            resp = await p.chat_complete([{"role": "user", "content": "hi"}])
    assert resp.content == "plain text answer"


# ---------------------------------------------------------------------------
# _serialize
# ---------------------------------------------------------------------------


def test_serialize_single_user_message_verbatim():
    assert CursorProvider._serialize([{"role": "user", "content": "just ask"}]) == "just ask"


def test_serialize_multi_turn_transcript():
    out = CursorProvider._serialize(
        [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]
    )
    assert out == "USER: Q1\n\nASSISTANT: A1\n\nUSER: Q2"


def test_serialize_skips_empty_content():
    out = CursorProvider._serialize(
        [{"role": "user", "content": "keep"}, {"role": "assistant", "content": ""}]
    )
    assert out == "keep"


# ---------------------------------------------------------------------------
# _parse_output
# ---------------------------------------------------------------------------


def test_parse_output_empty():
    assert CursorProvider._parse_output("") == ("", None)


def test_parse_output_json_returns_text_and_meta():
    content, meta = CursorProvider._parse_output(
        json.dumps({"result": "x", "is_error": False, "subtype": "success"})
    )
    assert content == "x"
    assert meta["is_error"] is False


def test_parse_output_non_json():
    content, meta = CursorProvider._parse_output("just text")
    assert content == "just text"
    assert meta is None
