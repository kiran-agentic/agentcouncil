from __future__ import annotations

import abc
import asyncio
import os
import shutil
import subprocess
import tempfile
import warnings
from typing import Any

__all__ = [
    "AgentAdapter", "AdapterError", "CodexAdapter", "ClaudeAdapter", "CursorAdapter",
    "StubAdapter", "CodexSession", "CodexSessionAdapter",
    "VALID_BACKENDS", "VALID_LEAD_BACKENDS",
    "resolve_outside_backend", "resolve_outside_adapter",
    "resolve_lead_settings", "resolve_lead_backend", "resolve_lead_adapter",
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

        Internal subclasses (CodexAdapter, ClaudeAdapter, CursorAdapter,
        StubAdapter, CodexSessionAdapter) are defined in agentcouncil.adapters and
        are exempted. External subclasses (e.g. OutsideSessionAdapter in
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
        return await asyncio.to_thread(self.call, prompt)


class CodexAdapter(AgentAdapter):
    """Invokes the local `codex exec` CLI to produce a response."""

    def __init__(self, model: str | None = None, timeout: int = 900, cwd: str | None = None) -> None:
        if not shutil.which("codex"):
            raise EnvironmentError("codex CLI not found on PATH")
        self._model = model
        self._timeout = timeout
        self._cwd = cwd

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
            effective_cwd = self._cwd
            if effective_cwd is None:
                try:
                    from agentcouncil.server import _get_workspace_sync
                    effective_cwd = _get_workspace_sync()
                except Exception:
                    effective_cwd = None
            subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
                cwd=effective_cwd,
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

    def __init__(self, model: str | None = None, timeout: int = 900, cwd: str | None = None) -> None:
        if not shutil.which("claude"):
            raise EnvironmentError("claude CLI not found on PATH")
        self._model = model
        self._timeout = timeout
        self._cwd = cwd

    def call(self, prompt: str) -> str:
        cmd = [
            "claude",
            "--print",
            "--output-format",
            "text",
            "--no-session-persistence",
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        # Resolve cwd at call time — picks up the server's resolved workspace
        # even if the adapter was constructed before workspace resolution.
        effective_cwd = self._cwd
        if effective_cwd is None:
            try:
                from agentcouncil.server import _get_workspace_sync
                effective_cwd = _get_workspace_sync()
            except Exception:
                effective_cwd = None
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
                cwd=effective_cwd,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise AdapterError(
                f"claude -p failed (exit {e.returncode}): {e.stderr}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"claude -p timed out after {self._timeout}s") from e


class CursorAdapter(AgentAdapter):
    """Invokes the local `cursor-agent` CLI as a one-shot subprocess (lead side).

    Used as the lead adapter in library mode when the host is Cursor. The prompt is
    passed as the trailing positional argument and the plain-text response is read
    from stdout (``--output-format text``).
    """

    def __init__(self, model: str | None = None, timeout: int = 900, cwd: str | None = None) -> None:
        if not shutil.which("cursor-agent"):
            raise EnvironmentError("cursor-agent CLI not found on PATH")
        self._model = model
        self._timeout = timeout
        self._cwd = cwd

    def call(self, prompt: str) -> str:
        cmd = [
            "cursor-agent",
            "--print",
            "--output-format",
            "text",
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        cmd.append(prompt)
        # Resolve cwd at call time — picks up the server's resolved workspace
        # even if the adapter was constructed before workspace resolution.
        effective_cwd = self._cwd
        if effective_cwd is None:
            try:
                from agentcouncil.server import _get_workspace_sync
                effective_cwd = _get_workspace_sync()
            except Exception:
                effective_cwd = None
        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
                cwd=effective_cwd,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise AdapterError(
                f"cursor-agent failed (exit {e.returncode}): {e.stderr}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"cursor-agent timed out after {self._timeout}s") from e


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


VALID_BACKENDS = ("codex", "claude", "cursor")
VALID_LEAD_BACKENDS = VALID_BACKENDS


def resolve_outside_backend(backend: str | None = None) -> str:
    """Resolve outside agent backend from arg > env var > host default.

    Precedence:
        1. Explicit ``backend`` argument (per-invocation)
        2. ``AGENTCOUNCIL_OUTSIDE_AGENT`` environment variable (global default)
        3. The host platform AgentCouncil is running under — "the backend it runs
           on" (Claude Code → ``"claude"``, Codex → ``"codex"``, Cursor →
           ``"cursor"``). Falls back to ``"claude"`` when no host is identified, so
           behaviour is unchanged out of the box inside Claude Code.

    Raises:
        ValueError: if the resolved backend is not in VALID_BACKENDS.
    """
    from agentcouncil.host import default_backend_for_host

    resolved = (
        backend
        or os.environ.get("AGENTCOUNCIL_OUTSIDE_AGENT")
        or default_backend_for_host()
    )
    if resolved not in VALID_BACKENDS:
        raise ValueError(
            f"Unknown outside agent backend: {resolved!r}. "
            f"Valid backends: {', '.join(VALID_BACKENDS)}"
        )
    return resolved


def resolve_outside_adapter(
    backend: str | None = None,
    timeout: int = 900,
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
    elif resolved == "cursor":
        return CursorAdapter(model=model, timeout=timeout)
    else:
        raise ValueError(f"Unknown outside agent backend: {resolved}")


def resolve_lead_settings(
    backend: str | None = None,
    model: str | None = None,
    loader: Any | None = None,
    default_claude_model: str | None = None,
) -> tuple[str, str | None]:
    """Resolve lead provider/model from explicit args, config, and env."""
    if loader is None:
        from agentcouncil.config import ProfileLoader

        loader = ProfileLoader()

    resolved = loader.resolve_lead(profile_name=backend)
    if isinstance(resolved, str):
        provider_name = resolved
        effective_model = model
    else:
        provider_name = resolved.provider
        effective_model = model or resolved.model

    if provider_name not in VALID_LEAD_BACKENDS:
        raise ValueError(
            "Lead backend must be one of: "
            f"{', '.join(VALID_LEAD_BACKENDS)}. Got provider={provider_name!r}."
        )

    if provider_name == "claude" and default_claude_model is not None:
        effective_model = effective_model or default_claude_model

    return provider_name, effective_model


def resolve_lead_backend(
    backend: str | None = None,
    loader: Any | None = None,
) -> str:
    """Resolve the lead backend name.

    Lead resolution is independent from outside-agent resolution: outside
    default_profile and AGENTCOUNCIL_OUTSIDE_AGENT never affect this result.
    """
    provider_name, _ = resolve_lead_settings(backend=backend, loader=loader)
    return provider_name


def resolve_lead_adapter(
    backend: str | None = None,
    timeout: int = 900,
    model: str | None = None,
    cwd: str | None = None,
    loader: Any | None = None,
    default_claude_model: str | None = "opus",
) -> AgentAdapter:
    """Create an adapter for the lead agent.

    Supported lead providers are Claude, Codex and Cursor. Claude preserves the
    historical default model of "opus"; Codex and Cursor use their CLI default
    unless a model is supplied directly or by a named profile.
    """
    provider_name, effective_model = resolve_lead_settings(
        backend=backend,
        model=model,
        loader=loader,
        default_claude_model=default_claude_model,
    )
    if provider_name == "claude":
        return ClaudeAdapter(model=effective_model, timeout=timeout, cwd=cwd)
    if provider_name == "codex":
        return CodexAdapter(model=effective_model, timeout=timeout, cwd=cwd)
    if provider_name == "cursor":
        return CursorAdapter(model=effective_model, timeout=timeout, cwd=cwd)
    raise ValueError(f"Unknown lead backend: {provider_name}")


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
        timeout: int = 900,
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
