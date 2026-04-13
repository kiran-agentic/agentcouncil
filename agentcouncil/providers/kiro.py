"""agentcouncil.providers.kiro -- KiroProvider via kiro-cli ACP JSON-RPC 2.0 subprocess.

Connects to Kiro CLI via the Agent Communication Protocol (ACP). Unlike HTTP-based
providers, KiroProvider manages a long-lived subprocess with stateful sessions.

KIRO-01: Implements OutsideProvider via kiro-cli acp subprocess
KIRO-02: Two-process tree management with pgrep -P and staged SIGTERM
KIRO-03: auth_check detects missing credentials via filesystem pre-flight
KIRO-04: ACP session lifecycle (initialize -> session/new -> session/prompt -> TurnEnd)
KIRO-05: Permission requests automatically denied with JSON-RPC error
KIRO-06: Session history corruption detected and raised as ProviderError
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from agentcouncil.providers.base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
)

__all__ = ["KiroProvider"]

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120.0  # seconds per readline


class KiroProvider(OutsideProvider):
    """OutsideProvider backed by kiro-cli ACP JSON-RPC 2.0 subprocess.

    Args:
        cli_path  -- Path to kiro-cli binary (default: "kiro-cli" from PATH)
        workspace -- Working directory for the kiro-cli session
        timeout   -- Seconds to wait for each stdout readline (default: 120)
    """

    session_strategy: str = "persistent"
    workspace_access: str = "native"
    supports_runtime_tools: bool = False

    def __init__(
        self,
        cli_path: str | None = None,
        workspace: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._cli_path = cli_path or "kiro-cli"
        self._workspace = workspace or str(Path.cwd())
        self._timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._session_id: str | None = None
        self._req_id: int = 0
        self._started: bool = False

    # -- Request ID counter --

    def _next_req_id(self) -> int:
        rid = self._req_id
        self._req_id += 1
        return rid

    # -- Credential paths --

    @staticmethod
    def _credential_paths() -> list[Path]:
        """Return candidate credential DB paths (XDG_DATA_HOME, Linux default, macOS).

        Checks XDG_DATA_HOME first (if set), then the Linux default, then macOS.
        """
        paths: list[Path] = []
        # Honor XDG_DATA_HOME if set (takes priority over hardcoded default)
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            paths.append(Path(xdg_data) / "kiro-cli" / "data.sqlite3")
        # Linux default
        paths.append(Path.home() / ".local" / "share" / "kiro-cli" / "data.sqlite3")
        if sys.platform == "darwin":
            paths.append(
                Path.home() / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3"
            )
        return paths

    # -- OutsideProvider ABC --

    async def auth_check(self) -> None:
        """KIRO-03: Verify kiro-cli is installed and credentials exist."""
        # Check binary exists
        if shutil.which(self._cli_path) is None and not Path(self._cli_path).is_file():
            raise ProviderError(
                f"kiro-cli not found at '{self._cli_path}'. "
                "Install kiro-cli from https://kiro.dev/cli/"
            )
        # Check credential DB exists
        db_paths = self._credential_paths()
        db_path: Path | None = None
        for candidate in db_paths:
            if candidate.exists():
                db_path = candidate
                break
        if db_path is None:
            searched = ", ".join(str(p) for p in db_paths)
            raise ProviderError(
                f"Kiro credentials not found. Run: kiro-cli auth login\n"
                f"Searched: {searched}"
            )
        # Query token presence — check both known key variants
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                "SELECT value FROM auth_kv WHERE key IN "
                "('kirocli:social:token', 'kirocli:oidc:token') LIMIT 1"
            )
            row = cursor.fetchone()
            conn.close()
            if row is None:
                raise ProviderError(
                    "Kiro auth token not found in credentials database. "
                    "Run: kiro-cli auth login"
                )
        except sqlite3.Error as exc:
            raise ProviderError(
                f"Failed to verify Kiro credentials: {exc}. "
                "Run: kiro-cli auth login"
            ) from exc

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """KIRO-04: Send prompt via ACP session/prompt and return accumulated response."""
        if not self._started:
            await self._start()

        # Extract last user message
        last_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_msg = msg.get("content", "")
                break

        # Send session/prompt (CRITICAL: field is "prompt", not "content" -- issue #7144)
        req_id = self._next_req_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {
                "sessionId": self._session_id,
                "prompt": [{"type": "text", "text": last_msg}],
            },
        }

        try:
            await self._send_raw(request)
            # Read until turn completes (response or turn_end notification)
            text = await self._read_until_turn_end(req_id)
        except (ProviderError, asyncio.TimeoutError, OSError) as exc:
            # F1-fix: Reset provider state so next call starts a fresh subprocess
            # instead of writing to a dead pipe.
            logger.warning("Kiro session failed mid-turn, resetting: %s", exc)
            await self._stop()
            raise
        return ProviderResponse(content=text)

    async def close(self) -> None:
        """KIRO-02: Clean up subprocess and children."""
        await self._stop()

    # -- Subprocess lifecycle --

    async def _start(self) -> None:
        """Spawn kiro-cli acp subprocess and perform ACP handshake."""
        self._proc = await asyncio.create_subprocess_exec(
            self._cli_path, "acp", "--trust-all-tools",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self._do_initialize()
        await self._do_session_new()
        self._started = True

    async def _stop(self) -> None:
        """KIRO-02: Staged two-process teardown via pgrep -P.

        Also attempts process-group kill as a fallback for children that may
        have been reparented or detached (F5 robustness).
        """
        if self._proc is None:
            return
        pid = self._proc.pid
        # 1. Enumerate and SIGTERM all children via pgrep -P
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(pid)], capture_output=True, text=True
            )
            child_pids = [int(p) for p in result.stdout.split() if p.strip()]
            for child_pid in child_pids:
                try:
                    os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if child_pids:
                await asyncio.sleep(1.0)
        except Exception:
            logger.debug("pgrep -P %d failed, falling back to process group kill", pid)
        # 2. SIGTERM the main process
        try:
            self._proc.terminate()
            await asyncio.sleep(1.0)
        except Exception:
            pass
        # 3. Wait for exit with timeout, force-kill if needed
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            try:
                self._proc.kill()
            except Exception:
                pass
            # Fallback: try to signal the entire process group to catch
            # descendants that may have been reparented (e.g., detached helpers).
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        self._proc = None
        self._session_id = None
        self._started = False

    # -- ACP handshake --

    async def _do_initialize(self) -> None:
        """Send ACP initialize request and read response."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_req_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "agentcouncil", "version": "1.3.0"},
            },
        }
        await self._send_raw(request)
        await self._read_response(request["id"])

    async def _do_session_new(self) -> None:
        """Send session/new and store the sessionId."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_req_id(),
            "method": "session/new",
            "params": {"cwd": self._workspace, "mcpServers": []},
        }
        await self._send_raw(request)
        result = await self._read_response(request["id"])
        self._session_id = result["sessionId"]

    # -- JSON-RPC I/O --

    async def _send_raw(self, msg: dict) -> None:
        """Write a JSON-RPC message to subprocess stdin."""
        assert self._proc is not None and self._proc.stdin is not None
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def _read_response(self, expected_id: int) -> dict:
        """Read lines until we get a JSON-RPC response with matching id.

        ACP is strictly request-response: only one request is outstanding at a
        time, so out-of-order responses should never occur in practice.
        Non-matching messages are logged as warnings (not buffered) because the
        protocol has no replay use case. If ACP adds async notifications in the
        future, this method should be extended with a pending-message queue.
        """
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await asyncio.wait_for(
                self._proc.stdout.readline(), timeout=self._timeout
            )
            if not line:
                raise ProviderError("kiro-cli process closed stdout unexpectedly")
            try:
                msg = json.loads(line.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Ignoring malformed ACP line: %s (%s)", line[:200], exc)
                continue
            # Handle permission requests inline
            if "method" in msg and "id" in msg:
                if msg["method"] == "session/request_permission":
                    await self._deny_permission(msg["id"])
                    continue
            # Match response by id
            if msg.get("id") == expected_id:
                if "error" in msg:
                    self._handle_error(msg["error"])
                return msg.get("result", {})
            # Log unexpected messages instead of silently dropping
            logger.warning(
                "Unexpected ACP message while waiting for id=%d: %s",
                expected_id, msg,
            )

    async def _read_until_turn_end(self, prompt_req_id: int | None = None) -> str:
        """KIRO-04/05: Read ACP messages, accumulate text, deny permissions.

        Turn completion is detected by EITHER:
        - A session/update notification with sessionUpdate="turn_end"
        - The response to the session/prompt request (stopReason="end_turn")

        Both are valid ACP turn-completion signals. Real Kiro CLI (v1.29+)
        uses the response-based signal; the notification-based signal is kept
        for forward compatibility.
        """
        assert self._proc is not None and self._proc.stdout is not None
        chunks: list[str] = []
        while True:
            line = await asyncio.wait_for(
                self._proc.stdout.readline(), timeout=self._timeout
            )
            if not line:
                raise ProviderError("kiro-cli process closed stdout unexpectedly")
            try:
                msg = json.loads(line.decode())
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("Ignoring malformed ACP line: %s (%s)", line[:200], exc)
                continue

            # KIRO-05: Handle permission requests (server->client request with id)
            if "method" in msg and "id" in msg:
                if msg["method"] == "session/request_permission":
                    await self._deny_permission(msg["id"])
                    continue

            # Handle error responses (messages with id, no method, and error field)
            if "id" in msg and "method" not in msg and "error" in msg:
                self._handle_error(msg["error"])

            # Response-based turn completion: session/prompt response with
            # stopReason="end_turn" (Kiro CLI v1.29+)
            if (
                prompt_req_id is not None
                and msg.get("id") == prompt_req_id
                and "result" in msg
            ):
                stop_reason = msg["result"].get("stopReason", "")
                if stop_reason == "end_turn":
                    return "".join(chunks)

            # Handle session/update notifications
            if msg.get("method") == "session/update":
                update = msg.get("params", {}).get("update", {})
                kind = update.get("sessionUpdate")
                if kind == "agent_message_chunk":
                    text = update.get("content", {}).get("text", "")
                    if text:
                        chunks.append(text)
                elif kind == "turn_end":
                    return "".join(chunks)

            # Skip vendor-specific notifications (_kiro.dev/*)
            if msg.get("method", "").startswith("_kiro.dev/"):
                continue

    # -- Permission denial --

    async def _deny_permission(self, request_id: int) -> None:
        """KIRO-05: Deny a permission request with JSON-RPC error."""
        denial = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32001,
                "message": (
                    "Permission denied -- agentcouncil denies all "
                    "permission requests automatically"
                ),
            },
        }
        await self._send_raw(denial)
        logger.info("Denied permission request id=%d", request_id)

    # -- Error handling --

    def _handle_error(self, error: dict) -> None:
        """KIRO-06: Detect history corruption; raise ProviderError for all errors."""
        data = error.get("data", "")
        if "invalid conversation history" in str(data):
            raise ProviderError(
                "Kiro session history corruption detected (upstream issue #6110). "
                "This is a known Kiro bug. Start a new session to continue. "
                f"Original error: {data}"
            )
        raise ProviderError(
            f"Kiro ACP error (code={error.get('code')}): "
            f"{error.get('message')} data={data!r}"
        )
