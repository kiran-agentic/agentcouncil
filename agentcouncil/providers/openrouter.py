"""agentcouncil.providers.openrouter — OpenRouterProvider via the openai SDK with base_url swap.

Connects to OpenRouter's OpenAI-compatible API using `openai.AsyncOpenAI` with
a base_url override to https://openrouter.ai/api/v1.

PROV-03 implementation:
    - Inherits OutsideProvider ABC
    - Client created lazily (not at __init__ time) per CFG-06 — env var read at call time
    - tool_call.function.arguments is a JSON string in the OpenAI SDK — must json.loads()
    - auth_check() validates env var presence then verifies API key via GET /models
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import openai

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
    ToolCall,
)

__all__ = ["OpenRouterProvider"]


class OpenRouterProvider(OutsideProvider):
    """OutsideProvider backed by OpenRouter's OpenAI-compatible API.

    Args:
        model       — OpenRouter model string (e.g., "openai/gpt-4o", "anthropic/claude-3-5-sonnet")
        api_key_env — Name of the environment variable holding the OpenRouter API key
                      (default: "OPENROUTER_API_KEY")

    Usage::

        provider = OpenRouterProvider(model="openai/gpt-4o")
        await provider.auth_check()          # verify key is valid
        response = await provider.chat_complete(messages, tools=tools)

    Notes:
        - The openai.AsyncOpenAI client is created lazily in _get_client() — construction
          does NOT require the env var to be set (CFG-06: never store raw key at init time).
        - tc.function.arguments from the OpenAI SDK is a JSON **string** — this provider
          json.loads() it before storing in ToolCall.arguments.
        - auth_check uses httpx to GET /models with a Bearer token rather than relying
          on the openai SDK, to get clean 401 detection.
    """

    session_strategy: str = "replay"
    workspace_access: str = "assisted"
    supports_runtime_tools: bool = True

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, model: str, api_key_env: str = "OPENROUTER_API_KEY") -> None:
        self._model = model
        self._api_key_env = api_key_env

    def _get_client(self) -> openai.AsyncOpenAI:
        """Create and return an openai.AsyncOpenAI client with OpenRouter base_url.

        Reads the API key from the environment variable at call time (CFG-06).

        Raises:
            ProviderError: if the env var is not set
        """
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise ProviderError(
                f"OpenRouter API key not found. "
                f"Set the {self._api_key_env} environment variable."
            )
        return openai.AsyncOpenAI(
            base_url=self.OPENROUTER_BASE_URL,
            api_key=api_key,
        )

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages to OpenRouter and return a normalized ProviderResponse.

        Args:
            messages — OpenAI-style message list (role + content dicts)
            tools    — Optional list of tool definitions in OpenAI format

        Returns:
            ProviderResponse with content and/or tool_calls.
            Tool call arguments are parsed from JSON string to dict.

        Raises:
            ProviderError: on authentication failure or any API error
        """
        client = self._get_client()
        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
            response = await client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise ProviderError(
                f"OpenRouter authentication failed — check {self._api_key_env}: {exc}"
            ) from exc
        except Exception as exc:
            raise ProviderError(f"OpenRouter chat_complete failed: {exc}") from exc

        message = response.choices[0].message
        content: str | None = message.content or None

        tool_calls: list[ToolCall] = []
        raw_tool_calls = message.tool_calls or []
        for tc in raw_tool_calls:
            # CRITICAL: tc.function.arguments is a JSON string in the OpenAI SDK
            arguments = json.loads(tc.function.arguments)
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                )
            )

        return ProviderResponse(content=content, tool_calls=tool_calls)

    async def auth_check(self) -> None:
        """Verify the OpenRouter API key is valid by calling GET /models.

        Checks the env var is set first, then makes a real HTTP request to
        verify the key is accepted by OpenRouter.

        Raises:
            ProviderError: if the env var is missing or the API key is invalid (401)
        """
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise ProviderError(
                f"OpenRouter API key not found. "
                f"Set the {self._api_key_env} environment variable."
            )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.OPENROUTER_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if response.status_code == 401:
                raise ProviderError(
                    f"OpenRouter API key is invalid (401). "
                    f"Check the value of {self._api_key_env}."
                )
            response.raise_for_status()
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"OpenRouter auth_check failed: {exc}"
            ) from exc
