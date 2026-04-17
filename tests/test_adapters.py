from __future__ import annotations

import subprocess

import pytest

from agentcouncil.adapters import (
    AdapterError,
    AgentAdapter,
    ClaudeAdapter,
    CodexAdapter,
    StubAdapter,
)


# ---------------------------------------------------------------------------
# ADAPT-01: Abstract interface — AgentAdapter cannot be instantiated directly
# ---------------------------------------------------------------------------


def test_abstract_interface_not_instantiable():
    """AgentAdapter() raises TypeError because it has abstract methods."""
    with pytest.raises(TypeError):
        AgentAdapter()  # type: ignore[abstract]


def test_incomplete_adapter_raises():
    """A subclass of AgentAdapter that does not implement call() raises TypeError."""

    class IncompleteAdapter(AgentAdapter):
        pass  # missing call()

    with pytest.raises(TypeError):
        IncompleteAdapter()


# ---------------------------------------------------------------------------
# ADAPT-04: StubAdapter
# ---------------------------------------------------------------------------


def test_stub_implements_interface():
    """StubAdapter is an instance of AgentAdapter."""
    stub = StubAdapter("x")
    assert isinstance(stub, AgentAdapter)


def test_stub_returns_configured_response():
    """StubAdapter("resp").call("p") returns "resp"."""
    stub = StubAdapter("resp")
    assert stub.call("any prompt") == "resp"


def test_stub_records_calls():
    """After two calls stub.calls contains both prompts in order."""
    stub = StubAdapter("response")
    stub.call("p1")
    stub.call("p2")
    assert stub.calls == ["p1", "p2"]


def test_stub_sequence():
    """StubAdapter with a list pops responses in order."""
    stub = StubAdapter(["a", "b"])
    assert stub.call("first") == "a"
    assert stub.call("second") == "b"


def test_stub_exhausted_raises():
    """AdapterError is raised when the list of responses is consumed."""
    stub = StubAdapter(["only one"])
    stub.call("first")
    with pytest.raises(AdapterError):
        stub.call("second")


def test_stub_single_cycles():
    """StubAdapter with a single string cycles indefinitely (repeat=True)."""
    stub = StubAdapter("x")
    for _ in range(5):
        assert stub.call("p") == "x"


# ---------------------------------------------------------------------------
# ADAPT-02 / ADAPT-03: CodexAdapter and ClaudeAdapter implement AgentAdapter
# ---------------------------------------------------------------------------


def test_codex_implements_interface(monkeypatch):
    """isinstance(CodexAdapter(), AgentAdapter) is True."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/path" if name == "codex" else None)
    adapter = CodexAdapter()
    assert isinstance(adapter, AgentAdapter)


def test_claude_implements_interface(monkeypatch):
    """isinstance(ClaudeAdapter(), AgentAdapter) is True."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/path" if name == "claude" else None)
    adapter = ClaudeAdapter()
    assert isinstance(adapter, AgentAdapter)


# ---------------------------------------------------------------------------
# ADAPT-05: PATH check at init time
# ---------------------------------------------------------------------------


def test_codex_not_on_path(monkeypatch):
    """CodexAdapter.__init__ raises EnvironmentError when codex is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(EnvironmentError):
        CodexAdapter()


def test_claude_not_on_path(monkeypatch):
    """ClaudeAdapter.__init__ raises EnvironmentError when claude is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(EnvironmentError):
        ClaudeAdapter()


# ---------------------------------------------------------------------------
# ADAPT-02: CodexAdapter.call() subprocess invocation
# ---------------------------------------------------------------------------


def test_codex_call_subprocess_args(monkeypatch, tmp_path):
    """CodexAdapter.call() builds the correct subprocess command list."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        # Write mock content to the output file (the -o argument)
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        with open(output_path, "w") as f:
            f.write("mock codex response")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    result = adapter.call("hello")

    cmd = captured_cmd["cmd"]
    assert "codex" in cmd
    assert "exec" in cmd
    assert "--ephemeral" in cmd
    assert "--sandbox" in cmd
    assert "read-only" in cmd
    assert "-o" in cmd
    assert result == "mock codex response"


def test_codex_call_failure_raises_adapter_error(monkeypatch):
    """CodexAdapter.call() raises AdapterError on CalledProcessError."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="some error")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    with pytest.raises(AdapterError):
        adapter.call("prompt")


def test_codex_call_timeout_raises_adapter_error(monkeypatch):
    """CodexAdapter.call() raises AdapterError on TimeoutExpired."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    with pytest.raises(AdapterError):
        adapter.call("prompt")


# ---------------------------------------------------------------------------
# ADAPT-03: ClaudeAdapter.call() subprocess invocation
# ---------------------------------------------------------------------------


def test_claude_call_subprocess_args(monkeypatch):
    """ClaudeAdapter.call() builds the correct subprocess command list and passes prompt via stdin."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="mock response\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter()
    result = adapter.call("test prompt")

    cmd = captured["cmd"]
    assert "claude" in cmd
    assert "--print" in cmd
    assert "--output-format" in cmd
    assert "text" in cmd
    assert "--no-session-persistence" in cmd
    assert captured["input"] == "test prompt"
    assert result == "mock response"


def test_claude_call_failure_raises_adapter_error(monkeypatch):
    """ClaudeAdapter.call() raises AdapterError on CalledProcessError."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="claude error")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter()
    with pytest.raises(AdapterError):
        adapter.call("prompt")


def test_claude_call_timeout_raises_adapter_error(monkeypatch):
    """ClaudeAdapter.call() raises AdapterError on TimeoutExpired."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter()
    with pytest.raises(AdapterError):
        adapter.call("prompt")


# ---------------------------------------------------------------------------
# Model parameter and timeout forwarding
# ---------------------------------------------------------------------------


def test_codex_model_param_passed_to_subprocess(monkeypatch, tmp_path):
    """CodexAdapter(model='gpt-4') includes -m gpt-4 in the subprocess command."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        with open(output_path, "w") as f:
            f.write("response")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter(model="gpt-4")
    adapter.call("hello")

    cmd = captured_cmd["cmd"]
    assert "-m" in cmd
    model_idx = cmd.index("-m")
    assert cmd[model_idx + 1] == "gpt-4"


def test_codex_no_model_param_when_none(monkeypatch, tmp_path):
    """CodexAdapter(model=None) does NOT include -m in the subprocess command."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        with open(output_path, "w") as f:
            f.write("response")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    adapter.call("hello")

    assert "-m" not in captured_cmd["cmd"]


def test_claude_model_param_passed_to_subprocess(monkeypatch):
    """ClaudeAdapter(model='opus') includes --model opus in the subprocess command."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="response\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter(model="opus")
    adapter.call("hello")

    cmd = captured_cmd["cmd"]
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "opus"


def test_codex_timeout_forwarded_to_subprocess(monkeypatch, tmp_path):
    """CodexAdapter(timeout=60) passes timeout=60 to subprocess.run."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    captured_kwargs = {}

    def fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        with open(output_path, "w") as f:
            f.write("response")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter(timeout=60)
    adapter.call("hello")

    assert captured_kwargs["timeout"] == 60


def test_claude_timeout_forwarded_to_subprocess(monkeypatch):
    """ClaudeAdapter(timeout=90) passes timeout=90 to subprocess.run."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    captured_kwargs = {}

    def fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="response\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter(timeout=90)
    adapter.call("hello")

    assert captured_kwargs["timeout"] == 90


# ---------------------------------------------------------------------------
# Output handling edge cases
# ---------------------------------------------------------------------------


def test_claude_strips_whitespace_from_output(monkeypatch):
    """ClaudeAdapter.call() strips leading/trailing whitespace from stdout."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="  response\n\n  ", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter()
    assert adapter.call("test") == "response"


def test_codex_strips_whitespace_from_output(monkeypatch, tmp_path):
    """CodexAdapter.call() strips leading/trailing whitespace from file content."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    def fake_run(cmd, **kwargs):
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        with open(output_path, "w") as f:
            f.write("  response with spaces  \n\n")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    assert adapter.call("test") == "response with spaces"


def test_claude_prompt_passed_via_stdin(monkeypatch):
    """ClaudeAdapter.call() passes the exact prompt text as stdin input."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="response\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter()
    adapter.call("multi\nline\nprompt with special chars: ${}!")

    assert captured["input"] == "multi\nline\nprompt with special chars: ${}!"


def test_adapter_error_contains_useful_message(monkeypatch):
    """AdapterError from failed subprocess includes stderr content and exit code."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/claude" if name == "claude" else None)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(returncode=42, cmd=cmd, stderr="authentication failed")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = ClaudeAdapter()
    with pytest.raises(AdapterError, match="exit 42"):
        adapter.call("prompt")


def test_stub_call_records_exact_prompt_text():
    """StubAdapter.calls records the exact prompt strings passed to call()."""
    stub = StubAdapter("response")
    stub.call("prompt one\nwith newlines")
    stub.call("prompt two: special chars ${}!")
    assert stub.calls[0] == "prompt one\nwith newlines"
    assert stub.calls[1] == "prompt two: special chars ${}!"


def test_codex_temp_file_cleaned_up_on_success(monkeypatch, tmp_path):
    """CodexAdapter.call() removes the temp file after successful read."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    created_paths = []

    def fake_run(cmd, **kwargs):
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        created_paths.append(output_path)
        with open(output_path, "w") as f:
            f.write("response")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    adapter.call("test")

    import os
    assert len(created_paths) == 1
    assert not os.path.exists(created_paths[0]), "Temp file should be cleaned up"


def test_codex_temp_file_cleaned_up_on_failure(monkeypatch, tmp_path):
    """CodexAdapter.call() removes the temp file even when subprocess fails."""
    monkeypatch.setattr("shutil.which", lambda name: "/fake/codex" if name == "codex" else None)

    created_paths = []

    def fake_run(cmd, **kwargs):
        o_index = cmd.index("-o")
        output_path = cmd[o_index + 1]
        created_paths.append(output_path)
        with open(output_path, "w") as f:
            f.write("partial")
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="error")

    monkeypatch.setattr("subprocess.run", fake_run)

    adapter = CodexAdapter()
    with pytest.raises(AdapterError):
        adapter.call("test")

    import os
    assert len(created_paths) == 1
    assert not os.path.exists(created_paths[0]), "Temp file should be cleaned up even on failure"
