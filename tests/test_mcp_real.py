"""Real-run test harness for agentcouncil MCP server.

These tests invoke real codex and claude CLIs — no monkeypatching, no stubs.
They are marked with @pytest.mark.real and skipped by default in normal test runs.

Run with:
    python3 -m pytest tests/test_mcp_real.py -m real -v -s

The -s flag shows print output for human review of which consensus statuses were
produced. Expected duration: 4-8 minutes per test.

Purpose:
    REAL-01 through REAL-04 are validated here by running real brainstorm invocations
    through the MCP client in-process. Each test targets a topic designed to elicit a
    different consensus outcome. Because real agents are non-deterministic, no specific
    status is asserted — the human reviewer checks the printed output against REAL-02,
    REAL-03, and REAL-04 acceptance criteria.

    Claude Code MCP integration is verified separately via manual testing.
"""
from __future__ import annotations

import json
import shutil

import pytest
from fastmcp import Client

from agentcouncil.schemas import ConsensusStatus
from agentcouncil.server import mcp

# ---------------------------------------------------------------------------
# Module-level mark — all tests in this file are skipped by default.
# Run with: python3 -m pytest tests/test_mcp_real.py -m real -v -s
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.real


def _cli_available(name: str) -> bool:
    """Return True if `name` is on PATH."""
    return shutil.which(name) is not None


skip_no_codex = pytest.mark.skipif(
    not _cli_available("codex"),
    reason="codex CLI not on PATH",
)

skip_no_claude = pytest.mark.skipif(
    not _cli_available("claude"),
    reason="claude CLI not on PATH",
)

# Valid status values for assertion (string form after model_dump).
_VALID_STATUSES = {s.value for s in ConsensusStatus}


def _parse_result(result) -> dict:
    """Extract and parse the BrainstormResult dict from a FastMCP CallToolResult."""
    assert not result.is_error, f"Tool returned an error: {result}"
    assert result.data is not None, "result.data should not be None on success"

    data = result.data

    # data may be a dict already (in-process transport) or a JSON string
    # depending on FastMCP version — handle both.
    if isinstance(data, str):
        data = json.loads(data)

    assert "artifact" in data, f"'artifact' key missing from result: {list(data.keys())}"
    assert "transcript" in data, f"'transcript' key missing from result: {list(data.keys())}"
    return data


def _print_summary(label: str, data: dict) -> None:
    """Print a human-readable summary of the brainstorm result."""
    artifact = data["artifact"]
    status = artifact.get("status", "<missing>")
    direction = artifact.get("recommended_direction", "<missing>")
    agreements = artifact.get("agreement_points", [])
    disagreements = artifact.get("disagreement_points", [])

    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"STATUS: {status}")
    print(f"RECOMMENDED DIRECTION: {direction[:200]}{'...' if len(direction) > 200 else ''}")
    print(f"AGREEMENTS ({len(agreements)}): {agreements[:2]}")
    print(f"DISAGREEMENTS ({len(disagreements)}): {disagreements[:2]}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Test 1: Low-controversy topic — expected to produce `consensus`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.timeout(600)
@skip_no_codex
@skip_no_claude
async def test_real_consensus():
    """REAL-01, REAL-02: Real brainstorm on a low-controversy topic.

    Topic chosen to maximize likelihood of `consensus` status: type hints in Python
    are broadly considered good practice — most practitioners agree.

    Does NOT assert a specific status — real agents are non-deterministic.
    Human reviewer checks printed STATUS line against REAL-02 criteria.
    """
    topic = (
        "Should Python projects use type hints in function signatures? "
        "Consider: code readability, IDE support, runtime overhead, "
        "maintenance burden for small teams vs large codebases, and "
        "compatibility with older Python versions."
    )

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": topic})

    data = _parse_result(result)
    artifact = data["artifact"]

    # Structural assertions — always required regardless of status.
    assert "status" in artifact, "'status' field missing from artifact"
    assert artifact["status"] in _VALID_STATUSES, (
        f"artifact['status'] = {artifact['status']!r} is not a valid ConsensusStatus value. "
        f"Valid values: {_VALID_STATUSES}"
    )

    _print_summary("test_real_consensus", data)

    # Remind human reviewer what to check.
    print(f"REAL-01 PASS: brainstorm completed without AdapterError")
    print(f"REAL-02 CHECK: status={artifact['status']!r} (expect 'consensus' for this topic)")


# ---------------------------------------------------------------------------
# Test 2: Context-dependent topic — expected to produce `consensus_with_reservations`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.timeout(600)
@skip_no_codex
@skip_no_claude
async def test_real_reservations():
    """REAL-01, REAL-03: Real brainstorm on a context-dependent architecture question.

    Topic chosen to maximize likelihood of `consensus_with_reservations`: microservices
    vs monolith is a question where agents typically agree on the directional answer
    (start with a monolith for small teams) but have reservations about edge cases
    and context sensitivity.

    Does NOT assert a specific status — real agents are non-deterministic.
    Human reviewer checks printed STATUS line against REAL-03 criteria.
    """
    topic = (
        "Is it better to use microservices or a monolith for a new startup's first product? "
        "The startup has 2 engineers and needs to ship in 3 months. "
        "Consider: deployment complexity, team cognitive load, future scalability, "
        "operational overhead, and the risk of premature optimization. "
        "Provide a specific recommendation with reasoning."
    )

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": topic})

    data = _parse_result(result)
    artifact = data["artifact"]

    assert "status" in artifact, "'status' field missing from artifact"
    assert artifact["status"] in _VALID_STATUSES, (
        f"artifact['status'] = {artifact['status']!r} is not a valid ConsensusStatus value. "
        f"Valid values: {_VALID_STATUSES}"
    )

    _print_summary("test_real_reservations", data)

    print(f"REAL-01 PASS: brainstorm completed without AdapterError")
    print(
        f"REAL-03 CHECK: status={artifact['status']!r} "
        f"(expect 'consensus_with_reservations' for this topic)"
    )


# ---------------------------------------------------------------------------
# Test 3: Polarizing topic — expected to produce `unresolved_disagreement`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.timeout(600)
@skip_no_codex
@skip_no_claude
async def test_real_disagreement():
    """REAL-01, REAL-04: Real brainstorm on a deliberately polarizing topic.

    Topic chosen to maximize likelihood of `unresolved_disagreement`: open source
    vs proprietary software is a genuinely contested values question. The prompt
    instructs agents to take strong positions to maximize divergence.

    Does NOT assert a specific status — real agents are non-deterministic.
    Human reviewer checks printed STATUS line against REAL-04 criteria.
    """
    topic = (
        "Should all software be open source? "
        "Consider: economic sustainability for developers and companies, "
        "security through obscurity arguments vs security through transparency, "
        "competitive advantage and intellectual property, "
        "the role of open source in public infrastructure and government systems, "
        "and the tension between community benefit and individual incentive. "
        "Take a strong position. Do not hedge — commit to a clear stance."
    )

    async with Client(mcp) as client:
        result = await client.call_tool("brainstorm", {"context": topic})

    data = _parse_result(result)
    artifact = data["artifact"]

    assert "status" in artifact, "'status' field missing from artifact"
    assert artifact["status"] in _VALID_STATUSES, (
        f"artifact['status'] = {artifact['status']!r} is not a valid ConsensusStatus value. "
        f"Valid values: {_VALID_STATUSES}"
    )

    _print_summary("test_real_disagreement", data)

    print(f"REAL-01 PASS: brainstorm completed without AdapterError")
    print(
        f"REAL-04 CHECK: status={artifact['status']!r} "
        f"(expect 'unresolved_disagreement' or 'partial_failure' for this topic)"
    )
