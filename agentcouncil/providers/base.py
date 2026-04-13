"""agentcouncil.providers.base — OutsideProvider ABC, response models, StubProvider.

Provides:
    ToolCall         — Pydantic model for a single tool invocation
    ProviderResponse — Pydantic model for a completed chat_complete response
    ProviderError    — Exception raised on provider failures
    OutsideProvider  — Abstract base class all backend providers must implement
    StubProvider     — Deterministic test provider with pre-configured responses
"""
from __future__ import annotations

import abc
from typing import Any

from pydantic import BaseModel

__all__ = [
    "ToolCall",
    "ProviderResponse",
    "ProviderError",
    "OutsideProvider",
    "StubProvider",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    """A single tool invocation requested by the model.

    Fields:
        id        — Unique identifier for this tool call (from the model)
        name      — Name of the tool to invoke
        arguments — Key-value arguments to pass to the tool
    """

    id: str
    name: str
    arguments: dict[str, Any]


class ProviderResponse(BaseModel):
    """The result of a single chat_complete call.

    Fields:
        content    — Text content from the model (None if response is tool-only)
        tool_calls — Zero or more tool invocations requested by the model
    """

    content: str | None = None
    tool_calls: list[ToolCall] = []


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Raised when a provider call fails, times out, or encounters an error.

    Examples:
        - Authentication failure (auth_check)
        - Network or API error during chat_complete
        - StubProvider exhausted with no more responses
    """

    pass


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class OutsideProvider(abc.ABC):
    """Contract for an outside LLM backend that supports chat completion.

    Concrete providers must implement:
        chat_complete — Send messages and receive a ProviderResponse
        auth_check    — Verify credentials are valid (raise ProviderError if not)

    All methods are async to support both HTTP-based and local subprocess providers.

    Class-level capability attributes (UPROV-04):
        session_strategy:       "persistent" | "replay"
            "persistent" — provider maintains a session across chat_complete calls
                           (send only the latest message each turn)
            "replay"     — provider is stateless (send full message history each call)
        workspace_access:       "native" | "assisted" | "none"
            "native"     — provider has its own workspace tools (e.g., codex, kiro)
            "assisted"   — provider needs the read-only deliberation harness for workspace
            "none"       — provider has no workspace access at all
        supports_runtime_tools: True | False
            True         — provider supports tool calling via the OutsideRuntime harness
            False        — provider handles tooling natively (subprocess/MCP-based providers)
    """

    session_strategy: str = "replay"           # "persistent" | "replay"
    workspace_access: str = "assisted"         # "native" | "assisted" | "none"
    supports_runtime_tools: bool = True        # False for subprocess-based providers

    @abc.abstractmethod
    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send a list of messages to the provider and return a ProviderResponse.

        Args:
            messages — OpenAI-style message list (role + content dicts)
            tools    — Optional list of tool definitions in the provider's format

        Returns:
            ProviderResponse with content and/or tool_calls

        Raises:
            ProviderError: if the provider call fails
        """
        ...

    @abc.abstractmethod
    async def auth_check(self) -> None:
        """Verify that the provider's credentials are valid.

        Should complete silently on success.

        Raises:
            ProviderError: if authentication fails
        """
        ...

    async def close(self) -> None:
        """Release provider resources (subprocess, connections, etc.).

        Default is a no-op. Subprocess-based providers (e.g., KiroProvider)
        override this to terminate child processes.
        """
        pass


# ---------------------------------------------------------------------------
# StubProvider — deterministic test double
# ---------------------------------------------------------------------------


class StubProvider(OutsideProvider):
    """Deterministic test provider with pre-configured responses.

    Behaviors:
        - Single ProviderResponse: cycles indefinitely
        - List of ProviderResponse: returns in order, raises ProviderError on exhaustion
        - auth_check(): always passes silently
        - calls: records every messages list passed to chat_complete

    Args:
        responses — A single ProviderResponse (cycles) or list (consumed in order)
    """

    def __init__(self, responses: list[ProviderResponse] | ProviderResponse) -> None:
        if isinstance(responses, ProviderResponse):
            self._responses: list[ProviderResponse] = [responses]
            self._cycle = True  # single response — repeat indefinitely
        else:
            self._responses = list(responses)
            self._cycle = False
        self.calls: list[list[dict[str, Any]]] = []  # recorded for test assertions

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Return the next pre-configured response.

        Records messages in self.calls for assertion in tests.

        Raises:
            ProviderError: if the response list is exhausted
        """
        self.calls.append(messages)
        if self._cycle:
            return self._responses[0]
        if not self._responses:
            raise ProviderError("StubProvider exhausted — no more responses configured")
        return self._responses.pop(0)

    async def auth_check(self) -> None:
        """Auth check always passes for the stub provider."""
        return None
