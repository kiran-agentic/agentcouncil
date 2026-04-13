from __future__ import annotations

import abc
import os
import shutil
import subprocess
import tempfile
import warnings
from typing import Any

__all__ = [
    "AgentAdapter", "AdapterError", "CodexAdapter", "ClaudeAdapter",
    "StubAdapter", "CodexSession", "CodexSessionAdapter",
    "VALID_BACKENDS", "resolve_outside_backend", "resolve_outside_adapter",
]


class AdapterError(Exception):
    """Raised when an adapter call fails, times out, or returns non-zero exit."""

    pass


class AgentAdapter(abc.ABC):
    """Contract for making a single LLM call and returning a plain-text response.

    Deprecated:
        AgentAdapter is the legacy extension point. New backends should implement
        OutsideProvider instead. A DeprecationWarning is emitted at class definition
        time for any subclass defined outside agentcouncil.adapters.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Emit DeprecationWarning for subclasses defined outside this module.

        Internal subclasses (CodexAdapter, ClaudeAdapter, StubAdapter,
        CodexSessionAdapter) are defined in agentcouncil.adapters and are
        exempted. External subclasses (e.g. OutsideSessionAdapter in
        agentcouncil.session, or user-defined adapters) trigger the warning.
        """
        super().__init_subclass__(**kwargs)
        if cls.__module__ != __name__:
            warnings.warn(
                f"AgentAdapter is deprecated. Subclass OutsideProvider instead. "
                f"({cls.__name__} defined in {cls.__module__})",
                DeprecationWarning,
                stacklevel=2,
            )

    @abc.abstractmethod
    def call(self, prompt: str) -> str:
        """Send prompt to the LLM backend and return the response as a string.

        Raises:
            AdapterError: if the backend call fails, times out, or returns non-zero exit.
        """
        ...

    async def acall(self, prompt: str) -> str:
        """Async version of call. Override for truly async adapters (e.g. CodexSessionAdapter).

        Default implementation delegates to the synchronous call().
        """
        return self.call(prompt)


class CodexAdapter(AgentAdapter):
    """Invokes the local `codex exec` CLI to produce a response."""

    def __init__(self, model: str | None = None, timeout: int = 120) -> None:
        if not shutil.which("codex"):
            raise EnvironmentError("codex CLI not found on PATH")
        self._model = model
        self._timeout = timeout

    def call(self, prompt: str) -> str:
        with tempfile.NamedTemporaryFile(mode="r", suffix=".txt", delete=False) as f:
            output_path = f.name
        try:
            cmd = [
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "-o",
                output_path,
                prompt,
            ]
            if self._model:
                cmd.extend(["-m", self._model])
            subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
            with open(output_path) as f:
                return f.read().strip()
        except subprocess.CalledProcessError as e:
            raise AdapterError(
                f"codex exec failed (exit {e.returncode}): {e.stderr}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"codex exec timed out after {self._timeout}s") from e
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)


class ClaudeAdapter(AgentAdapter):
    """Invokes the local `claude` CLI as a subprocess, passing the prompt via stdin."""

    def __init__(self, model: str | None = None, timeout: int = 120) -> None:
        if not shutil.which("claude"):
            raise EnvironmentError("claude CLI not found on PATH")
        self._model = model
        self._timeout = timeout

    def call(self, prompt: str) -> str:
        cmd = [
            "claude",
            "--print",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--tools",
            "",  # disable all tools — pure text responder
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise AdapterError(
                f"claude -p failed (exit {e.returncode}): {e.stderr}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"claude -p timed out after {self._timeout}s") from e


class StubAdapter(AgentAdapter):
    """Returns pre-configured canned responses for use in deterministic tests."""

    def __init__(self, responses: list[str] | str = "stub response") -> None:
        if isinstance(responses, str):
            self._responses: list[str] = [responses]
            self._cycle = True  # single string — repeat indefinitely
        else:
            self._responses = list(responses)
            self._cycle = False
        self.calls: list[str] = []  # record all prompts for test assertions

    def call(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self._cycle:
            return self._responses[0]
        if not self._responses:
            raise AdapterError("StubAdapter exhausted — no more responses configured")
        return self._responses.pop(0)


VALID_BACKENDS = ("codex", "claude")


def resolve_outside_backend(backend: str | None = None) -> str:
    """Resolve outside agent backend from arg > env var > default.

    Precedence:
        1. Explicit ``backend`` argument (per-invocation)
        2. ``AGENTCOUNCIL_OUTSIDE_AGENT`` environment variable (global default)
        3. ``"claude"`` (default — works out of the box inside Claude Code)

    Raises:
        ValueError: if the resolved backend is not in VALID_BACKENDS.
    """
    resolved = backend if backend else os.environ.get("AGENTCOUNCIL_OUTSIDE_AGENT", "claude")
    if resolved not in VALID_BACKENDS:
        raise ValueError(
            f"Unknown outside agent backend: {resolved!r}. "
            f"Valid backends: {', '.join(VALID_BACKENDS)}"
        )
    return resolved


def resolve_outside_adapter(
    backend: str | None = None,
    timeout: int = 300,
    model: str | None = None,
) -> AgentAdapter:
    """Create an outside adapter for sync protocols (brainstorm).

    For async protocols (review/decide/challenge), use ``resolve_outside_backend()``
    and manage CodexSession or ClaudeAdapter directly.
    """
    resolved = resolve_outside_backend(backend)
    if resolved == "codex":
        return CodexAdapter(model=model, timeout=timeout)
    elif resolved == "claude":
        return ClaudeAdapter(model=model, timeout=timeout)
    else:
        raise ValueError(f"Unknown outside agent backend: {resolved}")


class CodexSession:
    """Manages a persistent Codex MCP session via codex mcp-server.

    Usage::

        async with CodexSession(model="o4-mini") as session:
            first = await session.send("Analyze this code")   # uses codex tool
            follow = await session.send("Now compare with X")  # uses codex-reply
    """

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
        self._client: Any = None  # fastmcp.Client at runtime
        self._thread_id: str | None = None

    async def __aenter__(self) -> CodexSession:
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
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)
        self._client = None
        self._thread_id = None
        return False

    async def send(self, prompt: str) -> str:
        """Send a prompt; uses codex() for first call, codex-reply() for subsequent."""
        if self._client is None:
            raise RuntimeError("CodexSession is not active — use 'async with'")
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
        """Extract threadId from MCP call result (structured_content or data)."""
        for attr in ("structured_content", "data"):
            obj = getattr(result, attr, None)
            if isinstance(obj, dict) and "threadId" in obj:
                return obj["threadId"]
        return None

    def _extract_text(self, result: Any) -> str:
        """Extract text content from MCP CallToolResult."""
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


class CodexSessionAdapter(AgentAdapter):
    """Wraps a CodexSession as an AgentAdapter for use in run_deliberation().

    Uses the persistent MCP session (COM-07) so all outside-agent turns
    within a single invocation share the same Codex thread.
    """

    def __init__(self, session: CodexSession) -> None:
        self._session = session

    def call(self, prompt: str) -> str:
        raise RuntimeError(
            "CodexSessionAdapter is async-only — use acall() inside run_deliberation()"
        )

    async def acall(self, prompt: str) -> str:
        try:
            return await self._session.send(prompt)
        except Exception as e:
            raise AdapterError(f"CodexSession send failed: {e}") from e
