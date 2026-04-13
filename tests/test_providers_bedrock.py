"""Tests for agentcouncil.providers.bedrock — BedrockProvider contract tests.

All tests use mocks — no real AWS connection or credentials needed.
asyncio_mode=auto is set in pyproject.toml, so no @pytest.mark.asyncio decorator needed.

Contract coverage:
    PROV-04 — converse() called via asyncio.to_thread()
    PROV-05 — toolUse/toolResult normalized to ToolCall/role=tool internal format
    PROV-07 — fresh boto3 client per chat_complete() call (no cached client)
    TEST-01 — contract tests for BedrockProvider alongside Ollama and OpenRouter tests
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Skip entire module gracefully if boto3 is not installed
boto3 = pytest.importorskip("boto3")
botocore = pytest.importorskip("botocore")
import botocore.exceptions  # noqa: E402 — imported after importorskip guard

from agentcouncil.providers.base import ProviderError, ProviderResponse, ToolCall  # noqa: E402
from agentcouncil.providers.bedrock import BedrockProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build a mock boto3 converse() response
# ---------------------------------------------------------------------------


def _make_converse_response(
    text: str | None = None,
    tool_uses: list[dict] | None = None,
) -> dict:
    """Build a mock boto3 converse() response dict matching the Bedrock API structure.

    Args:
        text      — Optional text content for the assistant response
        tool_uses — Optional list of toolUse dicts (toolUseId, name, input)

    Returns:
        Dict matching Bedrock converse() response structure
    """
    content: list[dict] = []
    if text is not None:
        content.append({"text": text})
    for tu in tool_uses or []:
        content.append({"toolUse": tu})

    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": content,
            }
        },
        "stopReason": "tool_use" if tool_uses else "end_turn",
    }


# ---------------------------------------------------------------------------
# Text response
# ---------------------------------------------------------------------------


async def test_bedrock_text_response():
    """chat_complete with text response returns ProviderResponse(content='hello', tool_calls=[])."""
    provider = BedrockProvider(model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    mock_client = MagicMock()
    mock_client.converse.return_value = _make_converse_response(text="hello")

    with patch.object(provider, "_make_client", return_value=mock_client):
        result = await provider.chat_complete([{"role": "user", "content": "hi"}])

    assert isinstance(result, ProviderResponse)
    assert result.content == "hello"
    assert result.tool_calls == []


# ---------------------------------------------------------------------------
# Tool use response — single tool call, dict arguments
# ---------------------------------------------------------------------------


async def test_bedrock_tool_use_response():
    """chat_complete with toolUse block returns ToolCall with dict arguments (not JSON string)."""
    provider = BedrockProvider(model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    mock_client = MagicMock()
    mock_client.converse.return_value = _make_converse_response(
        tool_uses=[
            {"toolUseId": "tu-001", "name": "read_file", "input": {"path": "foo.py"}}
        ]
    )

    with patch.object(provider, "_make_client", return_value=mock_client):
        result = await provider.chat_complete(
            [{"role": "user", "content": "read foo"}]
        )

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "tu-001"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "foo.py"}
    # PROV-05: Bedrock input is already a dict — must not be a JSON string
    assert isinstance(tc.arguments, dict)


# ---------------------------------------------------------------------------
# Multiple tool calls
# ---------------------------------------------------------------------------


async def test_bedrock_multiple_tool_calls():
    """chat_complete with 2 toolUse blocks returns 2 ToolCall objects."""
    provider = BedrockProvider(model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    mock_client = MagicMock()
    mock_client.converse.return_value = _make_converse_response(
        tool_uses=[
            {"toolUseId": "tu-001", "name": "read_file", "input": {"path": "a.py"}},
            {"toolUseId": "tu-002", "name": "search_repo", "input": {"query": "TODO"}},
        ]
    )

    with patch.object(provider, "_make_client", return_value=mock_client):
        result = await provider.chat_complete(
            [{"role": "user", "content": "do stuff"}]
        )

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].id == "tu-001"
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[1].id == "tu-002"
    assert result.tool_calls[1].name == "search_repo"


# ---------------------------------------------------------------------------
# Per-invocation client creation (PROV-07)
# ---------------------------------------------------------------------------


async def test_bedrock_client_created_per_invocation():
    """Two chat_complete calls create two separate boto3 clients (PROV-07)."""
    provider = BedrockProvider(model="test-model")
    mock_client = MagicMock()
    mock_client.converse.return_value = _make_converse_response(text="ok")

    call_count = 0

    def make_fresh_client():
        nonlocal call_count
        call_count += 1
        return mock_client

    with patch.object(provider, "_make_client", side_effect=make_fresh_client):
        await provider.chat_complete([{"role": "user", "content": "q1"}])
        await provider.chat_complete([{"role": "user", "content": "q2"}])

    assert call_count == 2  # new client per call — PROV-07


# ---------------------------------------------------------------------------
# Tool result grouping (PROV-05)
# ---------------------------------------------------------------------------


async def test_bedrock_tool_result_grouping():
    """Consecutive role='tool' messages are grouped into a single Bedrock user message."""
    provider = BedrockProvider(model="test-model")
    messages = [
        {"role": "user", "content": "do stuff"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "tc-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                },
                {
                    "id": "tc-2",
                    "type": "function",
                    "function": {"name": "search_repo", "arguments": '{"query": "x"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "tc-1", "content": "file contents"},
        {"role": "tool", "tool_call_id": "tc-2", "content": "search results"},
    ]

    bedrock_msgs = provider._translate_messages(messages)

    # The last translated message must be a single user message with 2 toolResult blocks
    last = bedrock_msgs[-1]
    assert last["role"] == "user"
    assert len(last["content"]) == 2

    result_ids = [block["toolResult"]["toolUseId"] for block in last["content"]]
    assert "tc-1" in result_ids
    assert "tc-2" in result_ids


# ---------------------------------------------------------------------------
# auth_check — no credentials
# ---------------------------------------------------------------------------


async def test_bedrock_auth_check_no_credentials():
    """auth_check raises ProviderError matching 'credentials' when AWS creds missing."""
    provider = BedrockProvider(model="test-model")
    mock_control_client = MagicMock()
    mock_control_client.list_foundation_models.side_effect = (
        botocore.exceptions.NoCredentialsError()
    )

    with patch("agentcouncil.providers.bedrock.boto3.client", return_value=mock_control_client):
        with pytest.raises(ProviderError, match="credentials"):
            await provider.auth_check()


# ---------------------------------------------------------------------------
# auth_check — ClientError
# ---------------------------------------------------------------------------


async def test_bedrock_auth_check_client_error():
    """auth_check raises ProviderError when list_foundation_models raises ClientError."""
    provider = BedrockProvider(model="test-model")
    mock_control_client = MagicMock()
    mock_control_client.list_foundation_models.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
        "ListFoundationModels",
    )

    with patch("agentcouncil.providers.bedrock.boto3.client", return_value=mock_control_client):
        with pytest.raises(ProviderError):
            await provider.auth_check()


# ---------------------------------------------------------------------------
# auth_check — success
# ---------------------------------------------------------------------------


async def test_bedrock_auth_check_success():
    """auth_check completes without exception when list_foundation_models succeeds."""
    provider = BedrockProvider(model="test-model")
    mock_control_client = MagicMock()
    mock_control_client.list_foundation_models.return_value = {"modelSummaries": []}

    with patch("agentcouncil.providers.bedrock.boto3.client", return_value=mock_control_client):
        await provider.auth_check()  # must not raise


# ---------------------------------------------------------------------------
# Tool translation
# ---------------------------------------------------------------------------


async def test_bedrock_translate_tools():
    """_translate_tools converts OpenAI tool spec to Bedrock toolConfig format."""
    provider = BedrockProvider(model="test-model")
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object"},
            },
        }
    ]

    result = provider._translate_tools(openai_tools)

    assert result == {
        "tools": [
            {
                "toolSpec": {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {"json": {"type": "object"}},
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# User message format
# ---------------------------------------------------------------------------


async def test_bedrock_user_message_format():
    """_translate_messages wraps string content in [{'text': ...}] block for Bedrock."""
    provider = BedrockProvider(model="test-model")
    result = provider._translate_messages([{"role": "user", "content": "hello"}])

    assert result == [{"role": "user", "content": [{"text": "hello"}]}]


# ---------------------------------------------------------------------------
# Tools passed to converse()
# ---------------------------------------------------------------------------


async def test_bedrock_chat_complete_with_tools():
    """chat_complete passes toolConfig to converse() when tools are provided."""
    provider = BedrockProvider(model="test-model")
    mock_client = MagicMock()
    mock_client.converse.return_value = _make_converse_response(text="ok")

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object"},
            },
        }
    ]

    with patch.object(provider, "_make_client", return_value=mock_client):
        await provider.chat_complete(
            [{"role": "user", "content": "hi"}],
            tools=openai_tools,
        )

    # Verify converse() was called with toolConfig keyword
    call_kwargs = mock_client.converse.call_args[1]
    assert "toolConfig" in call_kwargs
    assert "tools" in call_kwargs["toolConfig"]
