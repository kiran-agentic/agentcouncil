"""agentcouncil.providers.bedrock — BedrockProvider via boto3 bedrock-runtime converse() API.

Connects to AWS Bedrock-hosted models (Claude, Llama, Mistral) using the boto3
bedrock-runtime converse() API wrapped in asyncio.to_thread().

PROV-04 implementation:
    - Inherits OutsideProvider ABC
    - boto3 client created per-invocation (PROV-07) — no cached client stored on self
    - converse() is synchronous; wrapped in asyncio.to_thread() for async compat
    - toolUse.input is already a Python dict — no json.loads() needed (unlike OpenAI SDK)

PROV-05 implementation:
    - Incoming toolUse blocks normalized to ToolCall objects
    - Outgoing role="tool" messages grouped into single Bedrock user message with toolResult blocks

PROV-07 implementation:
    - No self._client attribute — fresh boto3 client created inside every chat_complete call
    - Ensures STS/IAM credentials are always fresh (avoids ExpiredTokenException mid-session)
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import boto3
import botocore.exceptions

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
    ToolCall,
)

__all__ = ["BedrockProvider"]


class BedrockProvider(OutsideProvider):
    """OutsideProvider backed by AWS Bedrock via boto3 converse() API.

    Args:
        model                     — Bedrock model ID (e.g., "anthropic.claude-3-5-sonnet-20241022-v2:0")
        region                    — AWS region (default: "us-east-1")
        aws_access_key_id_env     — Env var name for AWS access key (optional)
        aws_secret_access_key_env — Env var name for AWS secret access key (optional)
        aws_session_token_env     — Env var name for AWS session token (optional)

    Usage::

        provider = BedrockProvider(model="anthropic.claude-3-5-sonnet-20241022-v2:0")
        await provider.auth_check()
        response = await provider.chat_complete(messages, tools=tools)

    Notes:
        - boto3 client is created per-invocation (PROV-07) — credentials are always fresh.
          No self._client attribute exists on this class.
        - converse() is synchronous; wrapped in asyncio.to_thread() (PROV-04).
        - toolUse.input from Bedrock is already a dict — no json.loads() needed.
          Contrast with OpenAI SDK where function.arguments is a JSON string.
        - Consecutive role="tool" messages are grouped into one Bedrock user message (PROV-05).
        - System messages are skipped (Bedrock uses a separate system parameter —
          TODO: support system parameter in a future phase).
        - Users can also set AWS_DEFAULT_REGION env var; boto3 reads this automatically.
    """

    session_strategy: str = "replay"
    workspace_access: str = "assisted"
    supports_runtime_tools: bool = True

    def __init__(
        self,
        model: str,
        region: str = "us-east-1",
        aws_access_key_id_env: str | None = None,
        aws_secret_access_key_env: str | None = None,
        aws_session_token_env: str | None = None,
    ) -> None:
        self._model = model
        self._region = region
        self._key_env = aws_access_key_id_env
        self._secret_env = aws_secret_access_key_env
        self._token_env = aws_session_token_env
        # NOTE: No boto3 client created here — see _make_client() (PROV-07)

    def _build_client_kwargs(self) -> dict[str, Any]:
        """Build shared kwargs for boto3 client construction (region + credentials).

        If aws_access_key_id_env is set, reads explicit credentials from environment
        variables. Otherwise, boto3 uses its default credential chain.
        """
        kwargs: dict[str, Any] = {}
        if self._region:
            kwargs["region_name"] = self._region
        if self._key_env:
            key = os.environ.get(self._key_env, "")
            secret = os.environ.get(self._secret_env or "", "")
            if key and secret:
                kwargs["aws_access_key_id"] = key
                kwargs["aws_secret_access_key"] = secret
                if self._token_env:
                    token = os.environ.get(self._token_env, "")
                    if token:
                        kwargs["aws_session_token"] = token
        return kwargs

    def _make_client(self):
        """Create a fresh boto3 bedrock-runtime client. Called per-invocation (PROV-07)."""
        return boto3.client("bedrock-runtime", **self._build_client_kwargs())

    def _translate_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert OpenAI-style messages to Bedrock converse() format.

        Key translations:
        - role="user", content=str       -> role="user",  content=[{"text": str}]
        - role="assistant", content, tool_calls
                                         -> role="assistant", content=[text+toolUse blocks]
        - consecutive role="tool" msgs   -> single role="user", content=[toolResult blocks]
        - role="system"                  -> skip (TODO: use system parameter in future phase)

        Args:
            messages — OpenAI-style message list

        Returns:
            Bedrock-format message list
        """
        result: list[dict[str, Any]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg["role"]

            if role == "user":
                content_str = msg.get("content", "")
                result.append({"role": "user", "content": [{"text": content_str}]})
                i += 1

            elif role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    content_blocks.append({"text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    fn = tc["function"]
                    # tc.function.arguments is a JSON string in OpenAI-style messages
                    # (runtime stores tool call arguments as JSON string in the message dict)
                    content_blocks.append({
                        "toolUse": {
                            "toolUseId": tc["id"],
                            "name": fn["name"],
                            "input": json.loads(fn["arguments"]),
                        }
                    })
                result.append({"role": "assistant", "content": content_blocks})
                i += 1

            elif role == "tool":
                # Collect ALL consecutive role="tool" messages into ONE user message
                # with multiple toolResult blocks. Bedrock requires this grouping —
                # sending separate user messages per tool call causes ValidationException.
                tool_blocks: list[dict[str, Any]] = []
                while i < len(messages) and messages[i]["role"] == "tool":
                    tm = messages[i]
                    tool_blocks.append({
                        "toolResult": {
                            "toolUseId": tm["tool_call_id"],
                            "content": [{"text": tm.get("content", "")}],
                            "status": "success",
                        }
                    })
                    i += 1
                result.append({"role": "user", "content": tool_blocks})

            else:
                # System messages: skip — Bedrock uses a separate system parameter.
                # TODO: extract system messages and pass as system= parameter in a future phase.
                i += 1

        return result

    def _translate_tools(
        self, openai_tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Convert OpenAI-format tool specs to Bedrock toolConfig format.

        Args:
            openai_tools — List of OpenAI-style tool definitions with type/function structure

        Returns:
            Bedrock toolConfig dict: {"tools": [{"toolSpec": {...}}, ...]}
        """
        bedrock_tools: list[dict[str, Any]] = []
        for t in openai_tools:
            fn = t["function"]
            bedrock_tools.append({
                "toolSpec": {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "inputSchema": {"json": fn["parameters"]},
                }
            })
        return {"tools": bedrock_tools}

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages to AWS Bedrock via converse() and return a normalized ProviderResponse.

        Creates a fresh boto3 client per call (PROV-07), translates messages and tools
        to Bedrock format, calls converse() via asyncio.to_thread(), and normalizes the
        response back to internal ProviderResponse/ToolCall format.

        Args:
            messages — OpenAI-style message list (role + content dicts)
            tools    — Optional list of tool definitions in OpenAI function format

        Returns:
            ProviderResponse with content and/or tool_calls.
            ToolCall.arguments are already dicts (Bedrock returns toolUse.input as dict).

        Raises:
            ProviderError: on any Bedrock API error or unexpected exception
        """
        client = self._make_client()  # fresh per call — PROV-07
        bedrock_messages = self._translate_messages(messages)
        kwargs: dict[str, Any] = {
            "modelId": self._model,
            "messages": bedrock_messages,
        }
        if tools:
            kwargs["toolConfig"] = self._translate_tools(tools)

        try:
            response = await asyncio.to_thread(client.converse, **kwargs)
        except botocore.exceptions.ClientError as exc:
            raise ProviderError(f"Bedrock API error: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"Bedrock chat_complete failed: {exc}") from exc

        output_message = response["output"]["message"]
        content: str | None = None
        tool_calls: list[ToolCall] = []

        for block in output_message.get("content", []):
            if "text" in block:
                content = block["text"] or None
            elif "toolUse" in block:
                tu = block["toolUse"]
                # CRITICAL: tu["input"] is already a Python dict from Bedrock —
                # do NOT call json.loads() here (unlike OpenAI SDK's function.arguments).
                tool_calls.append(ToolCall(
                    id=tu["toolUseId"],
                    name=tu["name"],
                    arguments=tu["input"],
                ))

        return ProviderResponse(content=content, tool_calls=tool_calls)

    async def auth_check(self) -> None:
        """Verify AWS credentials are valid by calling list_foundation_models.

        Creates a separate bedrock control-plane client (not bedrock-runtime)
        since list_foundation_models is a control-plane API.

        Raises:
            ProviderError: if credentials are missing or the API call fails
        """
        control_client = boto3.client("bedrock", **self._build_client_kwargs())
        try:
            await asyncio.to_thread(control_client.list_foundation_models)
        except botocore.exceptions.NoCredentialsError as exc:
            raise ProviderError(
                "AWS credentials not found. Configure via AWS_ACCESS_KEY_ID/SECRET, "
                f"~/.aws/credentials, or an IAM role. Original error: {exc}"
            ) from exc
        except botocore.exceptions.ClientError as exc:
            raise ProviderError(
                f"Bedrock auth_check failed. Check AWS credentials and region "
                f"(current region: {self._region}). Original error: {exc}"
            ) from exc
        except Exception as exc:
            raise ProviderError(f"Bedrock auth_check failed: {exc}") from exc
