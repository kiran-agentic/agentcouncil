"""agentcouncil.providers.claude -- ClaudeProvider via claude CLI subprocess.

Connects to Claude Code CLI via `claude --print` subprocess. The first call uses
`--session-id <uuid>` to create a session; subsequent calls use `--resume <uuid>`
to continue it. Unlike the legacy ClaudeAdapter, ClaudeProvider implements the
OutsideProvider ABC and integrates with the full session/runtime stack
(OutsideRuntime tool harness, model config via BackendProfile, etc.).

Each provider instance maintains a stable UUID session_id, enabling the claude CLI
to resume the same conversation thread across multiple chat_complete calls. This
implements persistent sessions (UPROV-02): each call spawns a fresh subprocess
but resumes the same conversation context via the session_id.

The claude CLI is always available when running inside Claude Code, making this
the natural fallback when no other backend is configured.

Class-level capability attributes (UPROV-04):
    session_strategy:       "persistent" -- session ID is stable across calls
    workspace_access:       "native"     -- claude has its own workspace tools
    supports_runtime_tools: False        -- claude handles tooling natively
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from typing import Any

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
)

__all__ = ["ClaudeProvider"]

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 900.0  # seconds


class ClaudeProvider(OutsideProvider):
    """OutsideProvider backed by claude CLI subprocess with session resumption.

    Args:
        model      -- Model to use (e.g. "sonnet", "opus"). None uses CLI default.
        timeout    -- Seconds to wait for the subprocess to complete (default: 900).
        session_id -- Explicit session ID string. If None, a UUID is generated at
                      init time and reused across all chat_complete calls (UPROV-02).

    Class-level capability attributes (UPROV-04):
        session_strategy:       "persistent"
        workspace_access:       "native"
        supports_runtime_tools: False
    """

    session_strategy: str = "persistent"
    workspace_access: str = "native"
    supports_runtime_tools: bool = False

    def __init__(
        self,
        model: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        session_id: str | None = None,
        cwd: str | None = None,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._session_id = session_id or str(uuid.uuid4())
        self._first_call = True  # First call uses --session-id, subsequent use --resume
        self._cwd = cwd

    async def auth_check(self) -> None:
        """Verify claude CLI is on PATH."""
        if shutil.which("claude") is None:
            raise ProviderError(
                "claude CLI not found on PATH. "
                "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
            )

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send messages to claude CLI and return the response.

        First call uses --session-id to create the session. Subsequent calls
        use --resume to continue it (UPROV-02). The session ID is stable per
        provider instance, so concurrent instances do not collide. Only the
        last user message is sent.
        """
        # Extract last user message
        last_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_msg = msg.get("content", "")
                break

        cmd = [
            "claude",
            "--print",
            "--output-format", "text",
        ]
        if self._first_call:
            cmd.extend(["--session-id", self._session_id])
        else:
            cmd.extend(["--resume", self._session_id])
        if self._model:
            cmd.extend(["--model", self._model])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=last_msg.encode()),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderError(
                f"claude CLI timed out after {self._timeout}s"
            ) from exc
        except OSError as exc:
            raise ProviderError(f"Failed to run claude CLI: {exc}") from exc

        if proc.returncode != 0:
            raise ProviderError(
                f"claude CLI failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )

        self._first_call = False
        return ProviderResponse(content=stdout.decode(errors="replace").strip())
