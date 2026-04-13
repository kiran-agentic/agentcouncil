"""Tests for KiroProvider -- mock-based ACP contract tests.

All tests use mocks -- no real kiro-cli binary or credentials needed.
asyncio_mode=auto is set in pyproject.toml, so no @pytest.mark.asyncio decorator needed.

Contract coverage:
    KIRO-01 -- KiroProvider implements OutsideProvider ABC
    KIRO-02 -- Two-process tree management via pgrep -P + staged SIGTERM
    KIRO-03 -- auth_check detects missing credentials and missing binary
    KIRO-04 -- ACP session lifecycle (initialize -> session/new -> session/prompt -> TurnEnd)
    KIRO-05 -- Permission requests automatically denied with JSON-RPC error code -32001
    KIRO-06 -- Session history corruption detected and raised as ProviderError
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agentcouncil.providers.base import OutsideProvider, ProviderError, ProviderResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_proc(responses: list[dict]) -> MagicMock:
    """Create a mock subprocess with pre-configured stdout responses."""
    proc = MagicMock()
    proc.pid = 12345
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    lines = [json.dumps(r).encode() + b"\n" for r in responses]
    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(side_effect=lines)
    proc.stderr = MagicMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


def _create_credential_db(path: Path) -> None:
    """Create a minimal kiro-cli credential SQLite DB with token."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO auth_kv VALUES ('kirocli:social:token', 'fake-token')")
    conn.commit()
    conn.close()


# Standard ACP handshake responses: initialize response + session/new response
def _acp_handshake_responses(session_id: str = "sess-001") -> list[dict]:
    return [
        # initialize response
        {"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": 1, "serverInfo": {"name": "kiro"}}},
        # session/new response
        {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": session_id}},
    ]


# ---------------------------------------------------------------------------
# KIRO-01: isinstance check
# ---------------------------------------------------------------------------


def test_kiro_isinstance_outside_provider():
    """KiroProvider must be a subclass of OutsideProvider."""
    from agentcouncil.providers.kiro import KiroProvider
    assert issubclass(KiroProvider, OutsideProvider)
    provider = KiroProvider()
    assert isinstance(provider, OutsideProvider)


# ---------------------------------------------------------------------------
# KIRO-03: auth_check
# ---------------------------------------------------------------------------


async def test_auth_check_missing_binary_raises(tmp_path):
    """auth_check raises ProviderError when kiro-cli binary is not found."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider(cli_path="nonexistent-kiro-cli-xyz")
    with patch("shutil.which", return_value=None):
        with pytest.raises(ProviderError) as exc_info:
            await provider.auth_check()
    assert "Install kiro-cli" in str(exc_info.value)


async def test_auth_check_missing_db_raises(tmp_path):
    """auth_check raises ProviderError when the credential DB file is missing."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider(cli_path="kiro-cli")
    with patch("shutil.which", return_value="/usr/bin/kiro-cli"):
        # Patch _credential_paths to return a path that does not exist
        nonexistent = tmp_path / "no_such_dir" / "data.sqlite3"
        with patch.object(KiroProvider, "_credential_paths", return_value=[nonexistent]):
            with pytest.raises(ProviderError) as exc_info:
                await provider.auth_check()
    assert "kiro-cli auth login" in str(exc_info.value)


async def test_auth_check_passes_with_valid_db(tmp_path):
    """auth_check passes silently when binary and DB with token both exist."""
    from agentcouncil.providers.kiro import KiroProvider

    db_path = tmp_path / "data.sqlite3"
    _create_credential_db(db_path)
    provider = KiroProvider(cli_path="kiro-cli")
    with patch("shutil.which", return_value="/usr/bin/kiro-cli"):
        with patch.object(KiroProvider, "_credential_paths", return_value=[db_path]):
            # Should not raise
            await provider.auth_check()


# ---------------------------------------------------------------------------
# KIRO-04: ACP subprocess lifecycle
# ---------------------------------------------------------------------------


async def test_start_spawns_correct_command():
    """_start spawns kiro-cli acp --trust-all-tools via create_subprocess_exec."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider(cli_path="kiro-cli")
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await provider._start()

    mock_exec.assert_called_once()
    args = mock_exec.call_args[0]
    assert args[0] == "kiro-cli"
    assert args[1] == "acp"
    assert args[2] == "--trust-all-tools"


async def test_initialize_sends_correct_request():
    """_do_initialize sends jsonrpc 2.0 initialize with protocolVersion=1 and clientInfo."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    # First write call is the initialize request
    first_write = mock_proc.stdin.write.call_args_list[0][0][0]
    sent = json.loads(first_write.decode())
    assert sent["method"] == "initialize"
    assert sent["params"]["protocolVersion"] == 1
    assert "clientInfo" in sent["params"]
    assert sent["params"]["clientInfo"]["name"] == "agentcouncil"


async def test_session_new_stores_session_id():
    """_do_session_new sends session/new and stores the returned sessionId."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses(session_id="test-session-42")
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    assert provider._session_id == "test-session-42"


async def test_session_prompt_uses_prompt_field_not_content():
    """chat_complete sends session/prompt with 'prompt' field, NOT 'content' (issue #7144)."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    turn_end_responses = [
        # session/prompt acknowledgment (result)
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        # session/update notifications
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "hello"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc = _make_mock_proc(handshake + turn_end_responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider.chat_complete([{"role": "user", "content": "test prompt"}])

    # Find the session/prompt write call (3rd write: after initialize + session/new)
    writes = mock_proc.stdin.write.call_args_list
    prompt_write = None
    for w in writes:
        sent = json.loads(w[0][0].decode())
        if sent.get("method") == "session/prompt":
            prompt_write = sent
            break

    assert prompt_write is not None, "No session/prompt request was sent"
    params = prompt_write["params"]
    # CRITICAL: must use "prompt" field, not "content"
    assert "prompt" in params, "session/prompt must have 'prompt' field"
    assert "content" not in params, "session/prompt must NOT use 'content' field (issue #7144)"
    assert params["prompt"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# KIRO-04: read_until_turn_end accumulates chunks
# ---------------------------------------------------------------------------


async def test_read_until_turn_end_accumulates_chunks():
    """_read_until_turn_end accumulates multiple agent_message_chunk texts and returns on turn_end."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    prompt_and_updates = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "Hello, "}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "world"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "!"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc = _make_mock_proc(handshake + prompt_and_updates)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        response = await provider.chat_complete([{"role": "user", "content": "hi"}])

    assert response.content == "Hello, world!"


# ---------------------------------------------------------------------------
# KIRO-05: Permission denial
# ---------------------------------------------------------------------------


async def test_permission_request_denied_with_echoed_id():
    """Permission requests trigger denial response with echoed id and code -32001."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    responses_with_permission = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        # Permission request interleaved before turn content
        {"jsonrpc": "2.0", "id": 99, "method": "session/request_permission", "params": {"permission": "read_file"}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "response text"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc = _make_mock_proc(handshake + responses_with_permission)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        response = await provider.chat_complete([{"role": "user", "content": "do something"}])

    # Find the denial write
    writes = mock_proc.stdin.write.call_args_list
    denial = None
    for w in writes:
        sent = json.loads(w[0][0].decode())
        if "error" in sent and sent.get("id") == 99:
            denial = sent
            break

    assert denial is not None, "No denial response was written"
    assert denial["error"]["code"] == -32001
    assert denial["id"] == 99  # echoed request id


async def test_session_continues_after_permission_denial():
    """Session continues after permission denial -- more chunks arrive after denial."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    responses = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": 55, "method": "session/request_permission", "params": {}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "continued after denial"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc = _make_mock_proc(handshake + responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        response = await provider.chat_complete([{"role": "user", "content": "test"}])

    # Should have accumulated text from after the permission denial
    assert response.content == "continued after denial"


# ---------------------------------------------------------------------------
# KIRO-06: History corruption detection
# ---------------------------------------------------------------------------


async def test_history_corruption_raises_provider_error():
    """Errors with 'invalid conversation history' in data raise ProviderError mentioning issue #6110."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    responses = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        # Error response with corruption data
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {
                "code": -32603,
                "message": "Internal error",
                "data": "invalid conversation history: message count exceeded",
            },
        },
    ]
    mock_proc = _make_mock_proc(handshake + responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()
        provider._proc = mock_proc
        with pytest.raises(ProviderError) as exc_info:
            await provider._read_until_turn_end()

    assert "issue #6110" in str(exc_info.value)


async def test_other_errors_not_treated_as_corruption():
    """Other -32603 errors raise ProviderError with original message, not treated as history corruption."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    responses = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {
                "code": -32603,
                "message": "Internal server error: unrelated",
                "data": "some other failure",
            },
        },
    ]
    mock_proc = _make_mock_proc(handshake + responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()
        provider._proc = mock_proc
        with pytest.raises(ProviderError) as exc_info:
            await provider._read_until_turn_end()

    # Should NOT mention issue #6110
    assert "issue #6110" not in str(exc_info.value)
    # Should mention the original error
    assert "unrelated" in str(exc_info.value) or "some other failure" in str(exc_info.value) or "-32603" in str(exc_info.value)


# ---------------------------------------------------------------------------
# KIRO-02: Two-process teardown
# ---------------------------------------------------------------------------


async def test_stop_force_kills_on_timeout():
    """_stop calls proc.kill() when proc.wait() times out after terminate.

    When the subprocess does not exit within 2 seconds after SIGTERM, _stop must
    escalate to SIGKILL via proc.kill(). Simulates asyncio.TimeoutError from
    asyncio.wait_for wrapping proc.wait().
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)
    # Override wait to raise TimeoutError when wrapped by asyncio.wait_for
    mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    pgrep_result = MagicMock()
    pgrep_result.stdout = ""

    with patch("subprocess.run", return_value=pgrep_result), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        await provider._stop()

    # Force-kill must be called when wait times out
    mock_proc.kill.assert_called_once()


async def test_stop_resets_session_state():
    """After _stop completes, _proc, _session_id, and _started are all reset to falsy.

    Verifies state cleanup is unconditional -- even when children were SIGTERMed.
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses(session_id="reset-test-session")
    mock_proc = _make_mock_proc(handshake)
    mock_proc.pid = 55555

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    # Confirm state was set during start
    assert provider._proc is not None
    assert provider._session_id == "reset-test-session"
    assert provider._started is True

    pgrep_result = MagicMock()
    pgrep_result.stdout = "66666\n"  # one child process

    with patch("subprocess.run", return_value=pgrep_result), \
         patch("os.kill"), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await provider._stop()

    # All state must be reset after _stop
    assert provider._proc is None
    assert provider._session_id is None
    assert provider._started is False


async def test_stop_calls_pgrep_and_sigterm():
    """_stop enumerates children via pgrep -P and sends staged SIGTERMs."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)
    mock_proc.pid = 99999

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    pgrep_result = MagicMock()
    pgrep_result.stdout = "11111\n22222\n"

    with patch("subprocess.run", return_value=pgrep_result) as mock_run, \
         patch("os.kill") as mock_kill, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await provider._stop()

    # pgrep -P was called
    mock_run.assert_called_once()
    pgrep_args = mock_run.call_args[0][0]
    assert "pgrep" in pgrep_args
    assert "-P" in pgrep_args
    assert str(99999) in pgrep_args

    # SIGTERM sent to child PIDs
    import signal
    killed_pids = {c[0][0] for c in mock_kill.call_args_list}
    assert 11111 in killed_pids
    assert 22222 in killed_pids


async def test_close_calls_stop():
    """close() calls _stop() to clean up subprocess."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    pgrep_result = MagicMock()
    pgrep_result.stdout = ""

    with patch("subprocess.run", return_value=pgrep_result), \
         patch("os.kill"), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await provider.close()

    # After close, _proc should be None
    assert provider._proc is None
    assert provider._started is False


# ---------------------------------------------------------------------------
# KIRO-01: chat_complete returns ProviderResponse
# ---------------------------------------------------------------------------


async def test_chat_complete_returns_provider_response():
    """chat_complete calls _start if not started, sends session/prompt, returns ProviderResponse."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    responses = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "The answer is 42."}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc = _make_mock_proc(handshake + responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await provider.chat_complete([{"role": "user", "content": "What is the answer?"}])

    assert isinstance(result, ProviderResponse)
    assert result.content == "The answer is 42."
    assert result.tool_calls == []


# ---------------------------------------------------------------------------
# KTEST-01: ACP contract gap tests (Task 1 additions)
# ---------------------------------------------------------------------------


async def test_permission_denial_during_handshake():
    """Permission request arriving during _read_response (handshake phase) is denied inline.

    A permission request may arrive between the initialize request and its response.
    _read_response must deny it with code -32001 and continue waiting for the real
    response with the expected id.
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    # Inject a permission request between the initialize response and session/new response.
    # _acp_handshake_responses gives [init_resp, session_new_resp].
    # We insert a permission request before the init response, so _read_response must
    # skip it and continue to the real initialize response.
    responses = [
        # permission request arrives before initialize response
        {"jsonrpc": "2.0", "id": 77, "method": "session/request_permission", "params": {"permission": "read_file"}},
        # initialize response (id=0)
        {"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": 1, "serverInfo": {"name": "kiro"}}},
        # session/new response (id=1)
        {"jsonrpc": "2.0", "id": 1, "result": {"sessionId": "sess-handshake-test"}},
    ]
    mock_proc = _make_mock_proc(responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    # Verify permission was denied with id=77 and code=-32001
    writes = mock_proc.stdin.write.call_args_list
    denial = None
    for w in writes:
        sent = json.loads(w[0][0].decode())
        if "error" in sent and sent.get("id") == 77:
            denial = sent
            break

    assert denial is not None, "No denial response written during handshake"
    assert denial["error"]["code"] == -32001
    assert denial["id"] == 77

    # Handshake completed successfully -- session_id was stored
    assert provider._session_id == "sess-handshake-test"
    assert provider._started is True


async def test_stdout_eof_during_start_raises():
    """ProviderError is raised when stdout closes unexpectedly during the startup handshake.

    Simulates the subprocess closing stdout before session/new response is received.
    _read_response raises ProviderError on empty line (b'').
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    # initialize response arrives, then EOF before session/new response
    responses_with_eof: list[bytes] = [
        json.dumps({"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": 1, "serverInfo": {"name": "kiro"}}}).encode() + b"\n",
        b"",  # EOF -- stdout closed
    ]
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdout = MagicMock()
    mock_proc.stdout.readline = AsyncMock(side_effect=responses_with_eof)
    mock_proc.stderr = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(ProviderError) as exc_info:
            await provider._start()

    assert "closed stdout unexpectedly" in str(exc_info.value)


async def test_chat_complete_auto_starts_on_first_call():
    """chat_complete calls _start exactly once on first call; second call skips _start.

    Verifies the _started flag correctly gates repeated subprocess spawning.
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()

    def make_full_responses():
        handshake = _acp_handshake_responses()
        turn = [
            {"jsonrpc": "2.0", "id": 2, "result": {}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "first"}}}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
        ]
        return handshake + turn

    mock_proc = _make_mock_proc(make_full_responses())

    start_call_count = 0
    original_start = provider._start

    async def tracked_start():
        nonlocal start_call_count
        start_call_count += 1
        await original_start()

    provider._start = tracked_start  # type: ignore[method-assign]

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider.chat_complete([{"role": "user", "content": "hello"}])

    assert start_call_count == 1, "_start must be called exactly once on first call"
    assert provider._started is True

    # Second call -- _start should NOT be called again
    second_turn = [
        {"jsonrpc": "2.0", "id": 3, "result": {}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "second"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc.stdout.readline = AsyncMock(
        side_effect=[json.dumps(r).encode() + b"\n" for r in second_turn]
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider.chat_complete([{"role": "user", "content": "world"}])

    assert start_call_count == 1, "_start must NOT be called again on second call"


async def test_session_prompt_includes_session_id():
    """session/prompt request sent to stdin includes the sessionId from session/new.

    Verifies that chat_complete correctly wires the stored _session_id into the
    session/prompt params, not just the prompt text field.
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    expected_session_id = "my-special-session-id-999"
    handshake = _acp_handshake_responses(session_id=expected_session_id)
    turn_responses = [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "ok"}}}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "turn_end"}}},
    ]
    mock_proc = _make_mock_proc(handshake + turn_responses)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider.chat_complete([{"role": "user", "content": "hello"}])

    # Find the session/prompt write
    writes = mock_proc.stdin.write.call_args_list
    prompt_write = None
    for w in writes:
        sent = json.loads(w[0][0].decode())
        if sent.get("method") == "session/prompt":
            prompt_write = sent
            break

    assert prompt_write is not None, "No session/prompt request was sent"
    assert prompt_write["params"]["sessionId"] == expected_session_id, (
        f"sessionId in session/prompt must be '{expected_session_id}', "
        f"got {prompt_write['params'].get('sessionId')!r}"
    )


async def test_stop_handles_pgrep_failure_gracefully():
    """_stop terminates the main process even when pgrep raises FileNotFoundError.

    On systems without pgrep (or if it fails), _stop must fall through and still
    terminate the main subprocess -- the try/except Exception block is tested here.
    """
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    with patch("subprocess.run", side_effect=FileNotFoundError("pgrep not found")), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await provider._stop()

    # Main process must still be terminated even when pgrep fails
    mock_proc.terminate.assert_called_once()


def test_stop_when_no_proc_is_noop():
    """_stop() returns immediately without error when _proc is None.

    Tests the guard condition at the top of _stop (line 177 of kiro.py).
    This is a synchronous test because it never awaits anything -- the guard
    returns before any await. We call it via asyncio.run to exercise the coroutine.
    """
    import asyncio as _asyncio
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    assert provider._proc is None  # fresh instance has no proc

    # Should complete without error
    _asyncio.run(provider._stop())


# ---------------------------------------------------------------------------
# F1: Crash-recovery -- mid-turn failure resets state for next call
# ---------------------------------------------------------------------------


async def test_chat_complete_resets_state_on_mid_turn_crash():
    """F1: If _read_until_turn_end raises (e.g. EOF), provider state must be
    reset so the next chat_complete starts a fresh subprocess instead of
    writing to a dead pipe."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    # First proc: handshake succeeds, then EOF during turn
    mock_proc1 = _make_mock_proc(handshake + [])
    # After handshake, readline returns empty (EOF)
    original_side_effect = list(mock_proc1.stdout.readline.side_effect)
    original_side_effect.append(b"")  # EOF after handshake
    mock_proc1.stdout.readline = AsyncMock(side_effect=original_side_effect)

    # Second proc: full handshake + successful turn
    # Note: request IDs continue from where they left off (2=initialize, 3=session/new,
    # 4=session/prompt), so handshake responses must use the continued IDs.
    handshake2 = [
        {"jsonrpc": "2.0", "id": 3, "result": {"protocolVersion": 1, "serverInfo": {"name": "kiro"}}},
        {"jsonrpc": "2.0", "id": 4, "result": {"sessionId": "sess-002"}},
    ]
    turn_response = {"method": "session/update", "params": {"update": {
        "sessionUpdate": "turn_end",
    }}}
    mock_proc2 = _make_mock_proc(handshake2 + [turn_response])

    call_count = {"n": 0}
    original_create = asyncio.create_subprocess_exec

    async def mock_create(*args, **kwargs):
        call_count["n"] += 1
        return mock_proc1 if call_count["n"] == 1 else mock_proc2

    messages = [{"role": "user", "content": "hello"}]

    with patch("asyncio.create_subprocess_exec", side_effect=mock_create), \
         patch("subprocess.run", return_value=MagicMock(stdout="")), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        # First call should fail with ProviderError (EOF)
        with pytest.raises(ProviderError, match="closed stdout"):
            await provider.chat_complete(messages)

        # After crash, state must be reset
        assert provider._started is False
        assert provider._proc is None

        # Second call should start a fresh subprocess
        result = await provider.chat_complete(messages)
        assert call_count["n"] == 2  # Two subprocesses spawned
        assert result.content == ""  # Empty turn (no chunks before turn_end)


# ---------------------------------------------------------------------------
# F2: Malformed stdout -- non-JSON lines are logged and skipped
# ---------------------------------------------------------------------------


async def test_read_response_handles_malformed_json():
    """F2: Non-JSON lines on stdout should be logged and skipped, not crash."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    # Simulate: malformed line, then valid response
    valid_response = {"jsonrpc": "2.0", "id": 99, "result": {"ok": True}}
    provider._proc.stdout.readline = AsyncMock(side_effect=[
        b"this is not json\n",
        json.dumps(valid_response).encode() + b"\n",
    ])

    result = await provider._read_response(99)
    assert result == {"ok": True}


async def test_read_until_turn_end_handles_malformed_json():
    """F2: Non-JSON lines during turn reading should be skipped."""
    from agentcouncil.providers.kiro import KiroProvider

    provider = KiroProvider()
    handshake = _acp_handshake_responses()
    mock_proc = _make_mock_proc(handshake)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await provider._start()

    turn_end = {"method": "session/update", "params": {"update": {
        "sessionUpdate": "turn_end",
    }}}
    provider._proc.stdout.readline = AsyncMock(side_effect=[
        b"binary garbage \xff\xfe\n",
        json.dumps(turn_end).encode() + b"\n",
    ])

    result = await provider._read_until_turn_end()
    assert result == ""  # No chunks, just turn_end


# ---------------------------------------------------------------------------
# F3: XDG_DATA_HOME -- credential path resolution honors XDG
# ---------------------------------------------------------------------------


def test_credential_paths_honors_xdg_data_home():
    """F3: _credential_paths() should check XDG_DATA_HOME first when set."""
    from agentcouncil.providers.kiro import KiroProvider

    with patch.dict("os.environ", {"XDG_DATA_HOME": "/custom/data"}):
        paths = KiroProvider._credential_paths()
        assert paths[0] == Path("/custom/data/kiro-cli/data.sqlite3")
        # Default path should still be present as fallback
        assert any(".local/share/kiro-cli" in str(p) for p in paths)


def test_credential_paths_without_xdg_data_home():
    """F3: Without XDG_DATA_HOME, first path should be the Linux default."""
    from agentcouncil.providers.kiro import KiroProvider
    import os

    env = dict(os.environ)
    env.pop("XDG_DATA_HOME", None)
    with patch.dict("os.environ", env, clear=True):
        paths = KiroProvider._credential_paths()
        assert ".local/share/kiro-cli" in str(paths[0])
