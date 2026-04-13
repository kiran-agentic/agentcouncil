"""agentcouncil.providers.codex -- CodexProvider via codex mcp-server persistent MCP session.

UPROV-01: Implements OutsideProvider using codex mcp-server for persistent session management.

Unlike the one-shot CodexSession adapter (adapters.py), CodexProvider exposes the
persistent MCP session as a first-class OutsideProvider. The session is lazily started
on first chat_complete() call, and is reused for all subsequent calls on the same
provider instance (using codex-reply to continue the thread).

Class-level capability attributes (UPROV-04):
    session_strategy:        "persistent" -- thread continues across chat_complete calls
    workspace_access:        "native"     -- codex mcp-server has its own workspace tools
    supports_runtime_tools:  False        -- codex handles tooling natively, not via OutsideRuntime
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
)

__all__ = ["CodexProvider"]


class CodexProvider(OutsideProvider):
    """OutsideProvider backed by codex mcp-server persistent MCP session.

    Args:
        model   -- Codex model name (e.g., "o4-mini"). None uses the Codex default.
        sandbox -- Codex sandbox mode (default: "read-only").
        timeout -- Seconds to wait per MCP call (default: 300).
        cwd     -- Working directory for the codex mcp-server subprocess.
                   Defaults to the current working directory at call time.

    Class-level capability attributes (UPROV-04):
        session_strategy:       "persistent"
        workspace_access:       "native"
        supports_runtime_tools: False

    Usage::

        provider = CodexProvider(model="o4-mini")
        await provider.auth_check()
        response = await provider.chat_complete(messages)
        await provider.close()
    """

    session_strategy: str = "persistent"
    workspace_access: str = "native"
    supports_runtime_tools: bool = False

    def __init__(
        self,
        model: str | None = None,
        sandbox: str = "read-only",
        timeout: int = 300,
        cwd: str | None = None,
    ) -> None:
        self._model = model
        self._sandbox = sandbox
        self._timeout = timeout
        self._cwd = cwd
        self._client: Any = None
        self._thread_id: str | None = None

    async def auth_check(self) -> None:
        """Verify codex CLI is on PATH.

        Raises:
            ProviderError: if codex CLI is not found on PATH.
        """
        if shutil.which("codex") is None:
            raise ProviderError(
                "codex CLI not found on PATH. "
                "Install from https://docs.openai.com/codex"
            )

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages to codex via persistent MCP session.

        Lazily starts the MCP session on first call.
        First message uses the "codex" tool; subsequent calls use "codex-reply"
        with the threadId from the first call (UPROV-01: persistent session).

        Args:
            messages -- OpenAI-style message list. Only the last user message is sent.
            tools    -- Ignored. codex mcp-server handles tools natively (UPROV-04).

        Returns:
            ProviderResponse with content from the codex response.

        Raises:
            ProviderError: if the session fails or codex returns an error.
        """
        if self._client is None:
            await self._start()
        last_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        text = await self._send(last_msg)
        return ProviderResponse(content=text)

    async def close(self) -> None:
        """Release the persistent MCP session.

        Idempotent — calling twice is safe and does not raise.
        """
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None
            self._thread_id = None

    async def _start(self) -> None:
        """Start the codex mcp-server subprocess and open the MCP client connection."""
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        transport = StdioTransport(
            command="codex",
            args=["mcp-server"],
            env={**os.environ},
            cwd=self._cwd or os.getcwd(),
        )
        self._client = Client(transport)
        await self._client.__aenter__()

    async def _send(self, prompt: str) -> str:
        """Send a prompt to codex, using codex-reply for subsequent calls.

        First call: uses the "codex" tool and captures threadId.
        Subsequent calls: uses "codex-reply" with the stored threadId.
        """
        if self._thread_id is None:
            params: dict[str, Any] = {"prompt": prompt, "sandbox": self._sandbox}
            if self._model:
                params["model"] = self._model
            result = await self._client.call_tool("codex", params)
            self._thread_id = self._extract_thread_id(result)
            return self._extract_text(result)
        else:
            result = await self._client.call_tool("codex-reply", {
                "prompt": prompt,
                "threadId": self._thread_id,
            })
            return self._extract_text(result)

    def _extract_thread_id(self, result: Any) -> str | None:
        """Extract threadId from MCP call result.

        Tries structured_content then data attributes (both are used by different
        fastmcp versions).
        """
        for attr in ("structured_content", "data"):
            obj = getattr(result, attr, None)
            if isinstance(obj, dict) and "threadId" in obj:
                return obj["threadId"]
        return None

    def _extract_text(self, result: Any) -> str:
        """Extract text content from an MCP CallToolResult.

        Tries result.text first, then iterates result.content for text items.
        Falls back to str(result) if neither is available.
        """
        if hasattr(result, "text") and result.text:
            return result.text
        if hasattr(result, "content"):
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
            if parts:
                return "\n".join(parts)
        return str(result)
