"""agentcouncil.providers.ollama — OllamaProvider via the official ollama Python SDK.

Connects to a locally-running Ollama instance (e.g., `ollama serve`) using
`ollama.AsyncClient` with stream=False for tool-calling sessions.

PROV-02 implementation:
    - Inherits OutsideProvider ABC
    - Generates synthetic tool call IDs (ollama-0, ollama-1, ...) since Ollama
      does not return tool_call_id in its API responses
    - auth_check() calls client.list() to verify reachability; wraps failures
      in ProviderError with actionable message mentioning ollama serve
"""
from __future__ import annotations

import json
from typing import Any

import ollama

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
    ToolCall,
)

__all__ = ["OllamaProvider"]


class OllamaProvider(OutsideProvider):
    """OutsideProvider backed by a local Ollama instance via the official Python SDK.

    Args:
        model    — Ollama model name (e.g., "llama3", "mistral", "qwen2.5-coder")
        base_url — HTTP base URL for the Ollama server (default: http://localhost:11434)

    Usage::

        provider = OllamaProvider(model="llama3")
        await provider.auth_check()          # verify ollama is reachable
        response = await provider.chat_complete(messages, tools=tools)

    Notes:
        - The SDK client is created at init time; no network call occurs on construction.
        - stream=False is always passed to chat() to get a single complete response.
        - Tool call IDs are synthetic: "ollama-0", "ollama-1", ... because the Ollama
          API does not return a tool_call_id field.
    """

    session_strategy: str = "replay"
    workspace_access: str = "assisted"
    supports_runtime_tools: bool = True

    def __init__(self, model: str, base_url: str = "http://localhost:11434") -> None:
        self._model = model
        self._base_url = base_url
        self._client = ollama.AsyncClient(host=base_url)

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages to Ollama and return a normalized ProviderResponse.

        Args:
            messages — OpenAI-style message list (role + content dicts)
            tools    — Optional list of tool definitions in Ollama format

        Returns:
            ProviderResponse with content and/or tool_calls.
            Tool call IDs are synthetic: f"ollama-{i}".

        Raises:
            ProviderError: on any SDK or network error
        """
        # Ollama's Python client expects tool_calls.function.arguments as a dict,
        # but OutsideRuntime serializes them as JSON strings (OpenAI format).
        # Normalize before sending to avoid pydantic validation errors on replay.
        normalized = []
        for msg in messages:
            if msg.get("tool_calls"):
                msg = dict(msg)
                msg["tool_calls"] = [
                    {
                        **tc,
                        "function": {
                            **tc["function"],
                            "arguments": (
                                json.loads(tc["function"]["arguments"])
                                if isinstance(tc["function"]["arguments"], str)
                                else tc["function"]["arguments"]
                            ),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
            normalized.append(msg)

        try:
            response = await self._client.chat(
                model=self._model,
                messages=normalized,
                tools=tools,
                stream=False,
            )
        except ollama.ResponseError as exc:
            raise ProviderError(f"Ollama API error: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"Ollama chat_complete failed: {exc}") from exc

        message = response.message
        content: str | None = message.content or None

        tool_calls: list[ToolCall] = []
        raw_tool_calls = message.tool_calls or []
        for i, tc in enumerate(raw_tool_calls):
            tool_calls.append(
                ToolCall(
                    id=f"ollama-{i}",
                    name=tc.function.name,
                    arguments=dict(tc.function.arguments),
                )
            )

        return ProviderResponse(content=content, tool_calls=tool_calls)

    async def auth_check(self) -> None:
        """Verify Ollama is reachable by calling client.list().

        Raises:
            ProviderError: if Ollama is not reachable, with an actionable message
                           mentioning the base_url and how to start Ollama.
        """
        try:
            await self._client.list()
        except Exception as exc:
            raise ProviderError(
                f"Ollama is not reachable at {self._base_url}. "
                f"Start it with: ollama serve — original error: {exc}"
            ) from exc
