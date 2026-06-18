"""agentcouncil.providers.cursor — CursorProvider via the ``cursor-agent`` CLI.

CursorProvider runs ``cursor-agent --print --output-format json`` as a subprocess
and returns the model's response. The ``--model`` flag selects which Cursor model
answers — independent of whatever model you have selected in the Cursor editor — so
a single deliberation can pit one Cursor model (e.g. ``gpt-5``) against another
(e.g. ``sonnet-4.5``). Run ``cursor-agent --list-models`` to see what your account
can use.

Session strategy is ``"replay"`` (stateless): the full accumulated conversation is
re-sent as a single prompt on every turn. This is a deliberate, conservative choice
— ``cursor-agent``'s ``--resume``/``session_id`` linkage was not verified against a
live binary during development, and a stateless replay is always correct (just less
token-efficient) and has no silent context-loss failure mode. If/when ``--resume`` is
confirmed to faithfully replay prior context, this provider could be upgraded to
``"persistent"`` for efficiency (mirroring ClaudeProvider).

Class-level capability attributes (UPROV-04):
    session_strategy:        "replay"   -- full history re-sent each turn (stateless)
    workspace_access:        "native"   -- cursor-agent reads the workspace itself
    supports_runtime_tools:  False      -- cursor-agent handles tooling natively
"""
from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
)

__all__ = ["CursorProvider"]

_DEFAULT_TIMEOUT = 900.0


class CursorProvider(OutsideProvider):
    """OutsideProvider backed by the ``cursor-agent`` CLI (stateless replay).

    Args:
        model   -- Cursor model name (e.g. ``"gpt-5"``, ``"sonnet-4.5"``, ``"auto"``).
                   None uses the CLI default.
        timeout -- Seconds to wait per subprocess call (default: 900).
        cwd     -- Working directory for cursor-agent. Defaults to the process CWD.

    Usage::

        provider = CursorProvider(model="gpt-5")
        await provider.auth_check()
        response = await provider.chat_complete(messages)
    """

    session_strategy: str = "replay"
    workspace_access: str = "native"
    supports_runtime_tools: bool = False

    def __init__(
        self,
        model: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        cwd: str | None = None,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._cwd = cwd

    async def auth_check(self) -> None:
        """Verify the cursor-agent CLI is on PATH.

        Raises:
            ProviderError: if the cursor-agent binary is not found.
        """
        if shutil.which("cursor-agent") is None:
            raise ProviderError(
                "cursor-agent CLI not found on PATH. "
                "Install the Cursor CLI (https://cursor.com/docs/cli) and "
                "authenticate with `cursor-agent login` (or set CURSOR_API_KEY)."
            )

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Send the full conversation to cursor-agent and return the response.

        Because the session strategy is ``"replay"``, the session layer passes the
        complete accumulated history each turn; it is serialized into a single
        prompt so cursor-agent always has the full context (no reliance on
        ``--resume``).

        Args:
            messages -- OpenAI-style message list (the full conversation).
            tools    -- Ignored. cursor-agent handles tools natively (UPROV-04).

        Raises:
            ProviderError: if the subprocess fails, times out, cannot start, or the
                response reports an in-band error (is_error / non-success subtype).
        """
        prompt = self._serialize(messages)

        cmd = ["cursor-agent", "--print", "--output-format", "json"]
        if self._model:
            cmd.extend(["--model", self._model])
        # Prompt is passed as the trailing positional argument (per cursor-agent
        # docs: `cursor-agent -p "<prompt>"`). The serialized transcript begins with
        # a role label / brief text, so it does not start with '-'. stdin is closed
        # so the CLI never blocks waiting for input.
        cmd.append(prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderError(
                f"cursor-agent timed out after {self._timeout}s"
            ) from exc
        except OSError as exc:
            raise ProviderError(f"Failed to run cursor-agent: {exc}") from exc

        if proc.returncode != 0:
            raise ProviderError(
                f"cursor-agent failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )

        content, meta = self._parse_output(stdout.decode(errors="replace"))

        # Catch in-band errors: cursor-agent can exit 0 but report a failure in the
        # JSON envelope (is_error / subtype != "success").
        if meta is not None:
            subtype = meta.get("subtype")
            if meta.get("is_error") is True or (
                isinstance(subtype, str) and subtype not in ("", "success")
            ):
                raise ProviderError(
                    f"cursor-agent reported an error (subtype={subtype!r}): "
                    f"{content or stdout.decode(errors='replace').strip()}"
                )

        return ProviderResponse(content=content)

    @staticmethod
    def _serialize(messages: list[dict[str, Any]]) -> str:
        """Flatten an OpenAI-style message list into a single prompt string.

        A lone user message is sent verbatim (clean single-turn prompt). Multi-turn
        conversations are rendered as a role-labelled transcript so cursor-agent has
        the full context on every (stateless) call.
        """
        msgs = [m for m in messages if m.get("content")]
        if not msgs:
            return ""
        if len(msgs) == 1 and msgs[0].get("role") == "user":
            return str(msgs[0].get("content", ""))
        parts = []
        for m in msgs:
            role = str(m.get("role", "user")).upper()
            parts.append(f"{role}: {m.get('content', '')}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_output(raw: str) -> tuple[str, dict[str, Any] | None]:
        """Parse cursor-agent ``--output-format json`` stdout into (text, meta).

        The non-streaming JSON form is a single object::

            {"type":"result","subtype":"success","result":"<text>",
             "is_error":false, "session_id":"...", ...}

        Returns the response text and the parsed JSON object (or None if the output
        was not valid JSON — a defensive fallback that returns the raw text).
        """
        text = raw.strip()
        if not text:
            return "", None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return text, None
        if not isinstance(obj, dict):
            return text, None
        content = obj.get("result")
        if content is None:
            content = obj.get("text") or obj.get("response") or ""
        if not isinstance(content, str):
            content = str(content)
        return content, obj
