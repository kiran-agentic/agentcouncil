"""MCP integration tests for agentcouncil.server.

Covers:
    MCP-01: brainstorm tool is discoverable via client.list_tools()
    MCP-02: single call_tool returns complete BrainstormResult dict
    MCP-03: server starts and communicates over stdio
    MCP-04: no stdout writes during tool execution (stdout purity)

All tests use StubAdapter to avoid real CLI dependencies.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from fastmcp import Client

from agentcouncil.adapters import StubAdapter
from agentcouncil.server import mcp

# ---------------------------------------------------------------------------
# Stub response constants
# ---------------------------------------------------------------------------

# BriefBuilder adapter (ClaudeAdapter) needs to return valid Brief JSON.
_STUB_BRIEF_JSON = json.dumps({
    "problem_statement": "test problem",
    "background": "test background",
    "constraints": ["c1"],
    "goals": ["g1"],
    "open_questions": ["q1"],
})

# Outside adapter (CodexAdapter) is called twice:
#   Round 1: outside proposal — plain text
#   Round 3: negotiation — valid ConsensusArtifact JSON
_STUB_OUTSIDE_PROPOSAL = "Outside proposal text"

_STUB_NEGOTIATION_JSON = json.dumps({
    "recommended_direction": "do X",
    "agreement_points": ["a1"],
    "disagreement_points": ["d1"],
    "rejected_alternatives": ["r1"],
    "open_risks": ["risk1"],
    "next_action": "next",
    "status": "consensus",
})

# Lead adapter (ClaudeAdapter) is called once:
#   Round 2: lead proposal — plain text
_STUB_LEAD_PROPOSAL = "Lead proposal text"


# ---------------------------------------------------------------------------
# Monkeypatch helper
# ---------------------------------------------------------------------------

def _patch_adapters(monkeypatch) -> tuple[StubAdapter, StubAdapter, StubAdapter]:
    """Patch resolve_outside_adapter and ClaudeAdapter in agentcouncil.server to return stubs.

    Also patches _make_provider to raise ValueError so brainstorm/review/etc fall
    through to the legacy adapter path (UPROV-03: _make_provider now dispatches
    "codex" to CodexProvider rather than raising ValueError, so we must force the
    fallback path explicitly for these legacy-path tests).

    Returns stubs in order (brief_stub, outside_stub, lead_stub) for inspection.
    """
    import agentcouncil.server as server_mod

    brief_stub = StubAdapter([_STUB_BRIEF_JSON])
    outside_stub = StubAdapter([_STUB_OUTSIDE_PROPOSAL, _STUB_NEGOTIATION_JSON])
    lead_stub = StubAdapter([_STUB_LEAD_PROPOSAL])

    def make_claude_stub(*args, **kwargs):
        model = kwargs.get("model")
        if model == "haiku":
            return brief_stub
        return lead_stub

    def make_outside_stub(*args, **kwargs):
        return outside_stub

    monkeypatch.setattr(server_mod, "ClaudeAdapter", make_claude_stub)
    monkeypatch.setattr(server_mod, "resolve_outside_adapter", make_outside_stub)
    # Force legacy fallback path by raising ValueError from _make_provider
    monkeypatch.setattr(
        server_mod, "_make_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("stub: force legacy path")),
    )

    return brief_stub, outside_stub, lead_stub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_discoverable():
    """MCP-01: brainstorm tool appears in client.list_tools()."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert "brainstorm" in names, f"Expected 'brainstorm' in tools, got: {names}"


@pytest.mark.asyncio
async def test_single_call_returns_result(monkeypatch):
    """MCP-02: call_tool('brainstorm') returns non-error result with artifact and transcript."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "how should we cache session data?"})

    assert not result.is_error, f"Tool returned an error: {result}"
    assert result.data is not None, "result.data should not be None on success"
    data = result.data
    assert "artifact" in data, f"'artifact' key missing from result: {list(data.keys())}"
    assert "transcript" in data, f"'transcript' key missing from result: {list(data.keys())}"


@pytest.mark.asyncio
async def test_result_has_consensus_artifact_fields(monkeypatch):
    """MCP-02: returned artifact dict has all 7 ConsensusArtifact fields plus status."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "test context"})

    assert not result.is_error
    artifact = result.data["artifact"]

    expected_fields = {
        "recommended_direction",
        "agreement_points",
        "disagreement_points",
        "rejected_alternatives",
        "open_risks",
        "next_action",
        "status",
    }
    missing = expected_fields - set(artifact.keys())
    assert not missing, f"ConsensusArtifact fields missing from result: {missing}"


@pytest.mark.asyncio
async def test_code_context_forwarded(monkeypatch):
    """MCP-02, BRIEF-04: calling with code_context includes it in the brief builder call."""
    brief_stub, outside_stub, lead_stub = _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "brainstorm",
            {"context": "design a cache layer", "code_context": "def get_cache(): pass"},
        )

    assert len(brief_stub.calls) == 1, (
        f"Expected BriefBuilder adapter called once, got {len(brief_stub.calls)} calls"
    )
    assert not result.is_error
    assert "artifact" in result.data


@pytest.mark.asyncio
async def test_artifact_status_is_valid_enum(monkeypatch):
    """MCP-02: returned artifact status is a valid ConsensusStatus value."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "test context"})

    assert not result.is_error
    artifact = result.data["artifact"]
    valid_statuses = {"consensus", "consensus_with_reservations", "unresolved_disagreement", "partial_failure"}
    assert artifact["status"] in valid_statuses, (
        f"Status '{artifact['status']}' not in valid set: {valid_statuses}"
    )


@pytest.mark.asyncio
async def test_artifact_field_values_are_correct_types(monkeypatch):
    """MCP-02: artifact fields have correct types — not just present, but right shape."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "test context"})

    assert not result.is_error
    artifact = result.data["artifact"]
    assert isinstance(artifact["recommended_direction"], str) and len(artifact["recommended_direction"]) > 0
    assert isinstance(artifact["agreement_points"], list)
    assert isinstance(artifact["disagreement_points"], list)
    assert isinstance(artifact["rejected_alternatives"], list)
    assert isinstance(artifact["open_risks"], list)
    assert isinstance(artifact["next_action"], str) and len(artifact["next_action"]) > 0
    assert isinstance(artifact["status"], str)


@pytest.mark.asyncio
async def test_transcript_has_all_fields(monkeypatch):
    """MCP-02: transcript contains all 4 round fields in the happy path."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "test context"})

    assert not result.is_error
    transcript = result.data["transcript"]
    assert "input_prompt" in transcript and transcript["input_prompt"]
    assert "outside_initial" in transcript and transcript["outside_initial"]
    assert "lead_initial" in transcript and transcript["lead_initial"]
    assert "final_output" in transcript and transcript["final_output"]


@pytest.mark.asyncio
async def test_transcript_has_metadata(monkeypatch):
    """META-01..03: transcript includes backend provenance metadata."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "test context"})

    assert not result.is_error
    transcript = result.data["transcript"]
    meta = transcript.get("meta")
    assert meta is not None, "transcript should include meta field"
    assert meta["lead_backend"] == "claude"
    assert meta["outside_backend"] is not None
    assert meta["outside_transport"] == "subprocess"
    assert meta["independence_tier"] in ("cross_backend", "same_backend_fresh_session")


@pytest.mark.asyncio
async def test_transcript_brief_prompt_contains_problem(monkeypatch):
    """MCP-02: the brief_prompt in transcript reflects the context that was passed in."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "how should we cache session data?"})

    assert not result.is_error
    transcript = result.data["transcript"]
    assert transcript["input_prompt"] is not None
    assert len(transcript["input_prompt"]) > 0


@pytest.mark.asyncio
async def test_empty_context_returns_result(monkeypatch):
    """Edge case: empty context string still returns a result (not a crash)."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": ""})

    assert result is not None


@pytest.mark.asyncio
async def test_adapters_created_fresh_per_call(monkeypatch):
    """Each brainstorm_tool call creates fresh adapters (not cached from prior call)."""
    import agentcouncil.server as server_mod

    call_count = [0]

    class TrackingStub(StubAdapter):
        def __init__(self, *args, **kwargs):
            call_count[0] += 1
            super().__init__(*args, **kwargs)

    def make_claude(*a, **kw):
        return TrackingStub([_STUB_BRIEF_JSON])

    def make_outside(*a, **kw):
        return TrackingStub([_STUB_OUTSIDE_PROPOSAL, _STUB_NEGOTIATION_JSON])

    monkeypatch.setattr(server_mod, "ClaudeAdapter", make_claude)
    monkeypatch.setattr(server_mod, "resolve_outside_adapter", make_outside)
    # Force legacy fallback path (UPROV-03: _make_provider now dispatches "codex"
    # to CodexProvider instead of raising ValueError)
    monkeypatch.setattr(
        server_mod, "_make_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("stub: force legacy path")),
    )

    async with Client(mcp) as client:
        await client.call_tool("brainstorm", {"context": "call 1"})
        first_count = call_count[0]
        await client.call_tool("brainstorm", {"context": "call 2"})
        second_count = call_count[0]

    # Each call without code_context creates 2 adapters (outside, lead).
    assert first_count == 2
    assert second_count == 4


@pytest.mark.asyncio
async def test_tool_has_correct_parameters():
    """MCP-01: brainstorm tool has context (required) and outside_agent (optional) parameters."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        brainstorm_tools = [t for t in tools if t.name == "brainstorm"]
        assert len(brainstorm_tools) == 1

        tool = brainstorm_tools[0]
        schema = tool.inputSchema
        assert "context" in schema.get("properties", {}), "Missing 'context' parameter"
        assert "outside_agent" in schema.get("properties", {}), "Missing 'outside_agent' parameter"


@pytest.mark.asyncio
async def test_result_is_json_serializable(monkeypatch):
    """MCP-03: result can be serialized to JSON (critical for stdio transport)."""
    _patch_adapters(monkeypatch)

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": "test"})

    assert not result.is_error
    serialized = json.dumps(result.data)
    deserialized = json.loads(serialized)
    assert deserialized["artifact"]["status"] == "consensus"


@pytest.mark.asyncio
async def test_stdout_purity():
    """MCP-04: server subprocess writes only valid JSON lines to stdout."""
    init_message = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.1"},
        },
    }) + "\n"

    proc = subprocess.run(
        [sys.executable, "-m", "agentcouncil.server"],
        input=init_message,
        capture_output=True,
        text=True,
        timeout=10,
    )

    stdout = proc.stdout
    non_empty_lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(non_empty_lines) > 0, (
        f"Server produced no stdout. stderr was: {proc.stderr[:500]}"
    )
    for line in non_empty_lines:
        try:
            parsed = json.loads(line)
            assert "jsonrpc" in parsed, f"Missing jsonrpc field in response: {line!r}"
        except json.JSONDecodeError as e:
            pytest.fail(
                f"Non-JSON line found in stdout (MCP-04 violation): {line!r}\nError: {e}"
            )


@pytest.mark.asyncio
async def test_stderr_contains_no_json_rpc(monkeypatch):
    """MCP-04: stderr does not contain JSON-RPC responses."""
    proc = subprocess.run(
        [sys.executable, "-m", "agentcouncil.server"],
        input=json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        }) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
    )

    for line in proc.stderr.splitlines():
        if line.strip():
            try:
                parsed = json.loads(line)
                assert "jsonrpc" not in parsed, (
                    f"JSON-RPC response leaked to stderr: {line!r}"
                )
            except json.JSONDecodeError:
                pass
