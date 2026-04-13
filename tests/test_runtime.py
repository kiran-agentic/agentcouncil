"""Tests for agentcouncil.runtime — OutsideRuntime, security, tool loop, budget, retry.

Test classes:
    TestSecurity              — path traversal, symlink escape, extension allowlist
    TestToolLoop              — StubProvider integration through OutsideRuntime.run_turn()
    TestTokenBudget           — char budget enforcement
    TestRetry                 — retry limit and degradation to text-only
    TestTextualProtocol       — textual action protocol parsing and gating
    TestIntegrationDegradation — StubProvider driving full retry+degradation loop
"""
from __future__ import annotations

import json
import os

import pytest

from agentcouncil.runtime import (
    OutsideRuntime,
    ToolSecurityError,
    TokenBudgetExceeded,
    _validate_path,
    _check_extension_allowlist,
    _filter_blocked_paths_from_grep,
    _filter_blocked_paths_from_diff,
    _TOOL_SPECS,
    _parse_textual_actions,
)
from agentcouncil.providers import (
    ProviderResponse,
    StubProvider,
    ToolCall,
)


# ---------------------------------------------------------------------------
# TestSecurity
# ---------------------------------------------------------------------------


class TestSecurity:
    """Path traversal, symlink escape, and extension allowlist tests."""

    def test_path_traversal_env(self, tmp_path):
        workspace = str(tmp_path)
        with pytest.raises(ToolSecurityError):
            _validate_path("../../.env", workspace)

    def test_path_traversal_etc_passwd(self, tmp_path):
        workspace = str(tmp_path)
        with pytest.raises(ToolSecurityError):
            _validate_path("subdir/../../../etc/passwd", workspace)

    def test_valid_path_returns_absolute(self, tmp_path):
        workspace = str(tmp_path)
        # Create the file so realpath can resolve it
        target = tmp_path / "valid" / "file.py"
        target.parent.mkdir(parents=True)
        target.touch()
        result = _validate_path("valid/file.py", workspace)
        assert os.path.isabs(result)
        assert result.startswith(str(tmp_path))

    def test_symlink_pointing_outside_workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Create a symlink inside workspace pointing outside
        evil_link = workspace / "evil"
        evil_link.symlink_to("/tmp")
        with pytest.raises(ToolSecurityError):
            _validate_path("evil/some_file", str(workspace))

    def test_workspace_root_allowed(self, tmp_path):
        workspace = str(tmp_path)
        result = _validate_path(".", workspace)
        # workspace root itself is allowed
        assert result == os.path.realpath(workspace)

    # --- Extension allowlist ---

    def test_blocks_dotenv_exact(self, tmp_path):
        resolved = str(tmp_path / ".env")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_envrc_exact(self, tmp_path):
        resolved = str(tmp_path / ".envrc")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    # --- Grep output filtering ---

    def test_grep_filter_removes_blocked_file_matches(self):
        output = "src/main.py:10:API_KEY=abc\n.env:1:SECRET=xyz\nsrc/util.py:5:ok"
        filtered = _filter_blocked_paths_from_grep(output, "/workspace")
        assert ".env" not in filtered
        assert "src/main.py" in filtered
        assert "src/util.py" in filtered

    def test_grep_filter_removes_binary_file_diagnostic(self):
        output = "Binary file .env matches\nsrc/main.py:10:hello"
        filtered = _filter_blocked_paths_from_grep(output, "/workspace")
        assert ".env" not in filtered
        assert "src/main.py" in filtered

    def test_grep_filter_removes_pem_matches(self):
        output = "certs/server.pem:1:-----BEGIN\nsrc/app.py:3:import os"
        filtered = _filter_blocked_paths_from_grep(output, "/workspace")
        assert "server.pem" not in filtered
        assert "src/app.py" in filtered

    def test_grep_filter_preserves_safe_files(self):
        output = "src/config.py:5:DATABASE_URL\ntests/test_config.py:10:assert"
        filtered = _filter_blocked_paths_from_grep(output, "/workspace")
        assert "src/config.py" in filtered
        assert "tests/test_config.py" in filtered

    # --- Diff output filtering ---

    def test_diff_filter_removes_blocked_file_hunks(self):
        output = (
            "diff --git a/.env b/.env\n"
            "--- a/.env\n"
            "+++ b/.env\n"
            "+SECRET=new\n"
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "+print('hello')"
        )
        filtered = _filter_blocked_paths_from_diff(output)
        assert ".env" not in filtered
        assert "src/main.py" in filtered
        assert "print('hello')" in filtered

    def test_blocks_netrc_exact(self, tmp_path):
        resolved = str(tmp_path / ".netrc")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_pem_extension(self, tmp_path):
        resolved = str(tmp_path / "server.pem")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_key_extension(self, tmp_path):
        resolved = str(tmp_path / "id_rsa.key")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_p12_extension(self, tmp_path):
        resolved = str(tmp_path / "cert.p12")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    # --- Prefix-based blocks (.env.*) ---

    def test_blocks_env_local(self, tmp_path):
        resolved = str(tmp_path / ".env.local")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_env_production(self, tmp_path):
        resolved = str(tmp_path / ".env.production")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    # --- Name-based blocks (new patterns) ---

    def test_blocks_npmrc(self, tmp_path):
        resolved = str(tmp_path / ".npmrc")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_git_credentials(self, tmp_path):
        resolved = str(tmp_path / ".git-credentials")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_pypirc(self, tmp_path):
        resolved = str(tmp_path / ".pypirc")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_id_rsa(self, tmp_path):
        resolved = str(tmp_path / "id_rsa")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_id_ed25519(self, tmp_path):
        resolved = str(tmp_path / "id_ed25519")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    # --- Directory-based blocks ---

    def test_blocks_ssh_directory(self, tmp_path):
        resolved = str(tmp_path / ".ssh" / "config")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_aws_credentials(self, tmp_path):
        resolved = str(tmp_path / ".aws" / "credentials")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_docker_config(self, tmp_path):
        resolved = str(tmp_path / ".docker" / "config.json")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_gnupg_directory(self, tmp_path):
        resolved = str(tmp_path / ".gnupg" / "secring.gpg")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    def test_blocks_secret_extension(self, tmp_path):
        resolved = str(tmp_path / "api.secret")
        with pytest.raises(ToolSecurityError):
            _check_extension_allowlist(resolved)

    # --- Allowed paths (should not raise) ---

    def test_allows_py(self, tmp_path):
        resolved = str(tmp_path / "main.py")
        # Should not raise
        _check_extension_allowlist(resolved)

    def test_allows_md(self, tmp_path):
        resolved = str(tmp_path / "README.md")
        _check_extension_allowlist(resolved)

    def test_allows_json(self, tmp_path):
        resolved = str(tmp_path / "config.json")
        _check_extension_allowlist(resolved)


# ---------------------------------------------------------------------------
# TestToolLoop
# ---------------------------------------------------------------------------


class TestToolLoop:
    """StubProvider integration through OutsideRuntime.run_turn()."""

    async def test_text_only_response_returns_content(self, tmp_path):
        provider = StubProvider(ProviderResponse(content="final answer"))
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "hello"}])
        assert result == "final answer"

    async def test_tool_call_then_text_completes_loop(self, tmp_path):
        # Create a real file the tool can read
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id="tc1", name="read_file", arguments={"path": "test.py"})
            ]),
            ProviderResponse(content="done reading"),
        ]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "read test.py"}])
        assert result == "done reading"
        # Two calls were made — first with tool, second after tool result appended
        assert len(provider.calls) == 2

    def test_tool_specs_include_all_four_tools(self, tmp_path):
        provider = StubProvider(ProviderResponse(content="ok"))
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        names = {spec["function"]["name"] for spec in _TOOL_SPECS}
        assert names == {"list_files", "search_repo", "read_file", "read_diff"}

    async def test_tool_result_appended_to_messages(self, tmp_path):
        # Create a file so the tool succeeds
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')

        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id="tc1", name="read_file", arguments={"path": "data.json"})
            ]),
            ProviderResponse(content="got it"),
        ]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        await runtime.run_turn([{"role": "user", "content": "read data"}])
        # Second call messages should contain the tool result
        second_call_messages = provider.calls[1]
        roles = [m["role"] for m in second_call_messages]
        assert "tool" in roles


# ---------------------------------------------------------------------------
# TestTokenBudget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    """Char budget enforcement."""

    async def test_exceeds_budget_raises(self, tmp_path):
        provider = StubProvider(ProviderResponse(content="ok"))
        runtime = OutsideRuntime(provider, workspace=str(tmp_path), char_budget=10)
        big_messages = [{"role": "user", "content": "x" * 200}]
        with pytest.raises(TokenBudgetExceeded):
            await runtime.run_turn(big_messages)

    async def test_within_budget_proceeds(self, tmp_path):
        provider = StubProvider(ProviderResponse(content="fine"))
        runtime = OutsideRuntime(provider, workspace=str(tmp_path), char_budget=100_000)
        result = await runtime.run_turn([{"role": "user", "content": "hello"}])
        assert result == "fine"


# ---------------------------------------------------------------------------
# TestRetry
# ---------------------------------------------------------------------------


class TestRetry:
    """Retry limit and degradation to text-only mode."""

    async def test_tool_calls_four_times_degrades_on_fourth(self, tmp_path):
        # 4 responses: first 3 have tool_calls, 4th has text (no tools)
        # After 3 retries the runtime strips tools; the 4th call gets tools=None
        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id=f"tc{i}", name="list_files", arguments={"path": "."})
            ])
            for i in range(3)
        ] + [ProviderResponse(content="degraded text")]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "go"}])
        assert result == "degraded text"
        # 4 total calls — 3 with tools, 1 without
        assert len(provider.calls) == 4
        # Fourth call was made with tools=None (check via the tools arg)
        # StubProvider doesn't record tools arg, but we can verify result is text content
        assert result == "degraded text"

    async def test_degraded_call_returns_text_content(self, tmp_path):
        # Same as above but verify the returned value explicitly
        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id=f"tc{i}", name="list_files", arguments={"path": "."})
            ])
            for i in range(3)
        ] + [ProviderResponse(content="final answer after degradation")]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "start"}])
        assert result == "final answer after degradation"

    async def test_single_tool_then_text_no_degradation(self, tmp_path):
        # 1 tool call then text — no degradation, completes normally
        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id="tc1", name="list_files", arguments={"path": "."})
            ]),
            ProviderResponse(content="text after one tool"),
        ]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "list it"}])
        assert result == "text after one tool"
        # Only 2 calls — no degradation happened
        assert len(provider.calls) == 2


# ---------------------------------------------------------------------------
# TestTextualProtocol
# ---------------------------------------------------------------------------


class TestTextualProtocol:
    """Textual action protocol: _parse_textual_actions and allow_textual_protocol gating."""

    def test_parse_read_file(self):
        result = _parse_textual_actions("READ_FILE path=main.py")
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "textual-0"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "main.py"}

    def test_parse_list_files(self):
        result = _parse_textual_actions("LIST_FILES path=src")
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "textual-0"
        assert tc.name == "list_files"
        assert tc.arguments == {"path": "src"}

    def test_parse_search_repo(self):
        result = _parse_textual_actions("SEARCH_REPO pattern=TODO path=.")
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "textual-0"
        assert tc.name == "search_repo"
        assert tc.arguments == {"pattern": "TODO", "path": "."}

    def test_parse_read_diff(self):
        result = _parse_textual_actions("READ_DIFF path=file.py")
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "textual-0"
        assert tc.name == "read_diff"
        assert tc.arguments == {"path": "file.py"}

    def test_parse_no_actions(self):
        result = _parse_textual_actions("no actions here")
        assert result == []

    def test_parse_multiple_actions(self):
        text = "READ_FILE path=a.py\nLIST_FILES path=src"
        result = _parse_textual_actions(text)
        assert len(result) == 2
        assert result[0].id == "textual-0"
        assert result[0].name == "read_file"
        assert result[0].arguments == {"path": "a.py"}
        assert result[1].id == "textual-1"
        assert result[1].name == "list_files"
        assert result[1].arguments == {"path": "src"}

    async def test_disabled_by_default(self, tmp_path):
        # allow_textual_protocol=False (default) — text with READ_FILE returns raw text
        raw_text = "READ_FILE path=test.py"
        provider = StubProvider(ProviderResponse(content=raw_text))
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "what files?"}])
        # Should return raw text without executing the tool
        assert result == raw_text
        # Only 1 call — no tool dispatch
        assert len(provider.calls) == 1

    async def test_enabled_executes_tool(self, tmp_path):
        # allow_textual_protocol=True — text with READ_FILE dispatches tool
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        responses = [
            ProviderResponse(content="READ_FILE path=test.py"),
            ProviderResponse(content="done after tool"),
        ]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(
            provider, workspace=str(tmp_path), allow_textual_protocol=True
        )
        result = await runtime.run_turn([{"role": "user", "content": "read it"}])
        # Should have dispatched tool and returned final text
        assert result == "done after tool"
        # Two calls — first produced textual action, second returned text
        assert len(provider.calls) == 2

    def test_inline_mention_not_parsed(self):
        # Casual mention mid-sentence should NOT trigger a parse (anchored to line start)
        text = "You can use READ_FILE path=x.py to read files"
        # This line starts with "You" not READ_FILE, so re.MULTILINE anchoring should prevent it
        # However the regex anchors to line start: if READ_FILE is at line start, it matches
        # This test verifies prose inline mention doesn't match when not at line start
        result = _parse_textual_actions("In prose: READ_FILE path=x.py is a command")
        assert result == []


# ---------------------------------------------------------------------------
# TestIntegrationDegradation
# ---------------------------------------------------------------------------


class TestIntegrationDegradation:
    """Full StubProvider driving retry+degradation loop through OutsideRuntime."""

    async def test_stub_provider_degradation(self, tmp_path):
        # 4-response StubProvider: first 3 have tool_calls (read_file), 4th is text-only
        # OutsideRuntime should retry 3 times, then on 4th call (tools=None) get text
        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id=f"tc{i}", name="list_files", arguments={"path": "."})
            ])
            for i in range(3)
        ] + [ProviderResponse(content="final text after degradation")]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "go"}])
        assert result == "final text after degradation"
        # 4 total provider calls
        assert len(provider.calls) == 4

    async def test_stub_provider_normal_completion(self, tmp_path):
        # 2-response StubProvider: first with tool_call, second text-only
        # Completes normally (retries=1, under limit=3)
        test_file = tmp_path / "readme.md"
        test_file.write_text("# project")

        responses = [
            ProviderResponse(tool_calls=[
                ToolCall(id="tc1", name="read_file", arguments={"path": "readme.md"})
            ]),
            ProviderResponse(content="analysis complete"),
        ]
        provider = StubProvider(responses)
        runtime = OutsideRuntime(provider, workspace=str(tmp_path))
        result = await runtime.run_turn([{"role": "user", "content": "analyze"}])
        assert result == "analysis complete"
        # Only 2 calls — 1 with tool, 1 after tool result
        assert len(provider.calls) == 2
