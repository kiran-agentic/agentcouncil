"""Tests for Deliberation Inspector — CLI Session Viewer (DI-01..DI-11)."""
from __future__ import annotations

import json

import pytest

from agentcouncil.schemas import (
    ConsensusStatus,
    JournalEntry,
    Transcript,
    TranscriptTurn,
)


def _make_journal_entry(**overrides):
    defaults = {
        "session_id": "inspect-001",
        "protocol_type": "review",
        "start_time": 1713100000.0,
        "end_time": 1713100060.0,
        "status": ConsensusStatus.consensus,
        "artifact": {"verdict": "pass", "summary": "Looks good"},
        "transcript": Transcript(
            input_prompt="Review this code",
            outside_initial="Outside review",
            lead_initial="Lead review",
            exchanges=[
                TranscriptTurn(role="outside", content="Exchange 1", phase="exchange"),
                TranscriptTurn(role="lead", content="Exchange 2", phase="exchange"),
            ],
            final_output="Synthesis result",
        ),
    }
    defaults.update(overrides)
    return JournalEntry(**defaults)


@pytest.fixture
def journal_dir(tmp_path):
    import agentcouncil.journal as jmod
    original = jmod.JOURNAL_DIR
    jmod.JOURNAL_DIR = tmp_path / "journal"
    yield tmp_path / "journal"
    jmod.JOURNAL_DIR = original


# ---------------------------------------------------------------------------
# DI-01, DI-02: Formatted output
# ---------------------------------------------------------------------------


def test_format_entry_returns_string(journal_dir):
    """DI-01, DI-02: format_entry produces a non-empty formatted string."""
    from agentcouncil.inspector import format_entry

    entry = _make_journal_entry()
    output = format_entry(entry)

    assert isinstance(output, str)
    assert len(output) > 0
    assert "review" in output.lower()


def test_format_entry_shows_turns(journal_dir):
    """DI-02: Formatted output shows turn details."""
    from agentcouncil.inspector import format_entry

    entry = _make_journal_entry()
    output = format_entry(entry)

    assert "outside" in output.lower()
    assert "lead" in output.lower()


# ---------------------------------------------------------------------------
# DI-03: Independence markers
# ---------------------------------------------------------------------------


def test_format_entry_marks_proposals(journal_dir):
    """DI-03: Proposal phases are marked in output."""
    from agentcouncil.inspector import format_entry

    entry = _make_journal_entry(
        transcript=Transcript(
            input_prompt="test",
            outside_initial="proposal",
            lead_initial="proposal",
            exchanges=[
                TranscriptTurn(role="outside", content="My proposal", phase="proposal"),
                TranscriptTurn(role="lead", content="My proposal", phase="proposal"),
            ],
        ),
    )
    output = format_entry(entry)
    assert "proposal" in output.lower()


# ---------------------------------------------------------------------------
# DI-08: JSON mode
# ---------------------------------------------------------------------------


def test_format_entry_json_mode(journal_dir):
    """DI-08: --json flag outputs raw JSON."""
    from agentcouncil.inspector import format_entry_json

    entry = _make_journal_entry()
    output = format_entry_json(entry)

    parsed = json.loads(output)
    assert parsed["session_id"] == "inspect-001"
    assert parsed["protocol_type"] == "review"


# ---------------------------------------------------------------------------
# DI-10: Unknown session error
# ---------------------------------------------------------------------------


def test_inspect_unknown_session(journal_dir):
    """DI-10: Inspecting unknown session gives actionable error."""
    from agentcouncil.inspector import inspect_session

    journal_dir.mkdir(parents=True, exist_ok=True)
    result = inspect_session("nonexistent")
    assert "not found" in result.lower() or "unknown" in result.lower()


# ---------------------------------------------------------------------------
# DI-11: List mode
# ---------------------------------------------------------------------------


def test_inspect_list(journal_dir):
    """DI-11: --list shows recent sessions."""
    from agentcouncil.journal import write_entry
    from agentcouncil.inspector import inspect_list

    write_entry(_make_journal_entry(session_id="s1"))
    write_entry(_make_journal_entry(session_id="s2", protocol_type="brainstorm"))

    output = inspect_list()
    assert "s1" in output
    assert "s2" in output
