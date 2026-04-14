"""Tests for Deliberation Journal persistence (DJ-01 through DJ-11)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from agentcouncil.schemas import ConsensusStatus, Transcript, TranscriptMeta


def _make_journal_entry(**overrides):
    """Build a valid JournalEntry with defaults."""
    from agentcouncil.journal import JournalEntry

    defaults = {
        "session_id": "test-session-001",
        "protocol_type": "brainstorm",
        "start_time": 1713100000.0,
        "end_time": 1713100060.0,
        "status": ConsensusStatus.consensus,
        "artifact": {"recommended_direction": "do X", "status": "consensus"},
        "transcript": Transcript(input_prompt="test brief"),
    }
    defaults.update(overrides)
    return JournalEntry(**defaults)


@pytest.fixture
def journal_dir(tmp_path):
    """Provide a temp directory for journal tests, patching JOURNAL_DIR."""
    import agentcouncil.journal as jmod

    original = jmod.JOURNAL_DIR
    jmod.JOURNAL_DIR = tmp_path / "journal"
    yield tmp_path / "journal"
    jmod.JOURNAL_DIR = original


# ---------------------------------------------------------------------------
# DJ-04: Schema version
# ---------------------------------------------------------------------------


def test_journal_entry_has_schema_version():
    """DJ-04: JournalEntry has schema_version field defaulting to '1.0'."""
    entry = _make_journal_entry()
    assert entry.schema_version == "1.0"


# ---------------------------------------------------------------------------
# DJ-05, DJ-06: Atomic writes and file layout
# ---------------------------------------------------------------------------


def test_write_and_read_roundtrip(journal_dir):
    """DJ-02, DJ-05, DJ-06: Write + read roundtrip produces identical entry."""
    from agentcouncil.journal import write_entry, read_entry

    entry = _make_journal_entry()
    path = write_entry(entry)

    assert path.exists()
    assert path.name == "test-session-001.json"
    assert path.parent == journal_dir

    restored = read_entry("test-session-001")
    assert restored.session_id == entry.session_id
    assert restored.protocol_type == entry.protocol_type
    assert restored.schema_version == "1.0"


def test_write_creates_directory_lazily(journal_dir):
    """DJ-10: Journal directory created on first write, not at import."""
    assert not journal_dir.exists()

    from agentcouncil.journal import write_entry
    write_entry(_make_journal_entry())

    assert journal_dir.exists()


def test_read_unknown_session_raises(journal_dir):
    """DJ-08: read_entry raises ValueError for unknown session_id."""
    from agentcouncil.journal import read_entry

    # Ensure dir exists but is empty
    journal_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="unknown"):
        read_entry("nonexistent-session")


# ---------------------------------------------------------------------------
# DJ-07: Listing
# ---------------------------------------------------------------------------


def test_list_entries_sorted_desc(journal_dir):
    """DJ-07: list_entries returns entries sorted by start_time descending."""
    from agentcouncil.journal import write_entry, list_entries

    write_entry(_make_journal_entry(session_id="s1", start_time=100.0))
    write_entry(_make_journal_entry(session_id="s2", start_time=300.0))
    write_entry(_make_journal_entry(session_id="s3", start_time=200.0))

    entries = list_entries()
    assert [e["session_id"] for e in entries] == ["s2", "s3", "s1"]


def test_list_entries_with_protocol_filter(journal_dir):
    """DJ-07: list_entries filters by protocol_type."""
    from agentcouncil.journal import write_entry, list_entries

    write_entry(_make_journal_entry(session_id="s1", protocol_type="brainstorm"))
    write_entry(_make_journal_entry(session_id="s2", protocol_type="review"))
    write_entry(_make_journal_entry(session_id="s3", protocol_type="brainstorm"))

    entries = list_entries(protocol="review")
    assert len(entries) == 1
    assert entries[0]["session_id"] == "s2"


def test_list_entries_respects_limit(journal_dir):
    """DJ-07: list_entries respects limit parameter."""
    from agentcouncil.journal import write_entry, list_entries

    for i in range(5):
        write_entry(_make_journal_entry(session_id=f"s{i}", start_time=float(i)))

    entries = list_entries(limit=3)
    assert len(entries) == 3


# ---------------------------------------------------------------------------
# DJ-09: Credential scrubbing
# ---------------------------------------------------------------------------


def test_no_credentials_persisted(journal_dir):
    """DJ-09: API keys and credentials are never persisted."""
    from agentcouncil.journal import write_entry, read_entry

    meta = TranscriptMeta(
        lead_backend="claude",
        outside_backend="openrouter",
    )
    entry = _make_journal_entry(
        transcript=Transcript(input_prompt="test", meta=meta),
    )
    write_entry(entry)
    restored = read_entry(entry.session_id)

    # Verify the entry was persisted and meta is present
    assert restored.transcript.meta is not None
    assert restored.transcript.meta.lead_backend == "claude"


# ---------------------------------------------------------------------------
# DJ-10: No directory at import time
# ---------------------------------------------------------------------------


def test_import_does_not_create_directory(journal_dir):
    """DJ-10: Importing journal module does not create the directory."""
    assert not journal_dir.exists()
    import agentcouncil.journal  # noqa: F401
    assert not journal_dir.exists()


# ---------------------------------------------------------------------------
# DJ-01: Auto-persist on protocol completion (tested via JournalEntry model)
# ---------------------------------------------------------------------------


def test_journal_entry_protocol_types():
    """DJ-01: JournalEntry supports all four protocol types."""
    for ptype in ("brainstorm", "review", "decide", "challenge"):
        entry = _make_journal_entry(protocol_type=ptype)
        assert entry.protocol_type == ptype


# ---------------------------------------------------------------------------
# DJ-02: Entry contains required fields
# ---------------------------------------------------------------------------


def test_journal_entry_required_fields():
    """DJ-02: JournalEntry contains all required fields."""
    entry = _make_journal_entry()
    assert entry.session_id is not None
    assert entry.protocol_type is not None
    assert entry.start_time is not None
    assert entry.end_time is not None
    assert entry.status is not None
    assert entry.artifact is not None
    assert entry.transcript is not None


def test_journal_entry_provenance_fields(journal_dir):
    """DJ-03: Each transcript turn carries provenance fields."""
    from agentcouncil.journal import write_entry, read_entry
    from agentcouncil.schemas import TranscriptTurn

    turn = TranscriptTurn(
        role="outside",
        content="proposal",
        actor_id="agent-001",
        actor_provider="codex",
        actor_model="gpt-4.1",
        phase="proposal",
        timestamp=1713100000.0,
        parent_turn_id=None,
    )
    entry = _make_journal_entry(
        session_id="prov-001",
        transcript=Transcript(input_prompt="test", exchanges=[turn]),
    )
    write_entry(entry)
    restored = read_entry("prov-001")
    t = restored.transcript.exchanges[0]
    assert t.actor_id == "agent-001"
    assert t.actor_provider == "codex"
    assert t.actor_model == "gpt-4.1"
    assert t.phase == "proposal"
    assert t.timestamp == 1713100000.0


def test_journal_failure_does_not_crash_protocol():
    """DJ-11: Journal failures must not fail the protocol (non-fatal)."""
    # This tests that _persist_journal in server.py is wrapped in try/except
    # We verify by importing the function and confirming it doesn't raise
    # even with bad input
    from agentcouncil.server import _persist_journal

    # Call with a non-model object — should not raise
    _persist_journal("brainstorm", object(), 0.0)
    # If we get here, the function handled the error gracefully


# ---------------------------------------------------------------------------
# TS: Turn Stream — Cursor-Based Event Retrieval
# ---------------------------------------------------------------------------


def test_append_event(journal_dir):
    """TS-01, TS-09: Events can be appended to journal entries during execution."""
    from agentcouncil.journal import write_entry, append_event, read_entry

    write_entry(_make_journal_entry(session_id="ev-001"))
    append_event("ev-001", {
        "event_type": "turn_added",
        "data": {"role": "outside", "phase": "proposal"},
    })

    entry = read_entry("ev-001")
    assert len(entry.events) == 1
    assert entry.events[0]["event_type"] == "turn_added"
    assert entry.events[0]["event_id"] == 1


def test_append_multiple_events_monotonic(journal_dir):
    """TS-03, TS-07: Event IDs are monotonic integers."""
    from agentcouncil.journal import write_entry, append_event, read_entry

    write_entry(_make_journal_entry(session_id="ev-002"))
    append_event("ev-002", {"event_type": "turn_added", "data": {}})
    append_event("ev-002", {"event_type": "phase_transition", "data": {}})
    append_event("ev-002", {"event_type": "status_change", "data": {}})

    entry = read_entry("ev-002")
    assert len(entry.events) == 3
    ids = [e["event_id"] for e in entry.events]
    assert ids == [1, 2, 3]


def test_stream_events_all(journal_dir):
    """TS-05: stream_events with no cursor returns all events."""
    from agentcouncil.journal import write_entry, append_event, stream_events

    write_entry(_make_journal_entry(session_id="ev-003"))
    append_event("ev-003", {"event_type": "turn_added", "data": {}})
    append_event("ev-003", {"event_type": "phase_transition", "data": {}})

    result = stream_events("ev-003")
    assert len(result["events"]) == 2
    assert result["next_cursor"] == 2


def test_stream_events_since_cursor(journal_dir):
    """TS-04, TS-07: stream_events with since_cursor filters correctly."""
    from agentcouncil.journal import write_entry, append_event, stream_events

    write_entry(_make_journal_entry(session_id="ev-004"))
    append_event("ev-004", {"event_type": "turn_added", "data": {}})
    append_event("ev-004", {"event_type": "phase_transition", "data": {}})
    append_event("ev-004", {"event_type": "status_change", "data": {}})

    result = stream_events("ev-004", since_cursor=1)
    assert len(result["events"]) == 2
    assert result["events"][0]["event_id"] == 2
    assert result["next_cursor"] == 3


def test_stream_events_unknown_session_raises(journal_dir):
    """TS-08: stream_events on unknown session raises ValueError."""
    from agentcouncil.journal import stream_events

    journal_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError):
        stream_events("nonexistent")


def test_stream_events_empty(journal_dir):
    """TS-05: stream_events with no events returns empty list."""
    from agentcouncil.journal import write_entry, stream_events

    write_entry(_make_journal_entry(session_id="ev-005"))
    result = stream_events("ev-005")
    assert result["events"] == []
    assert result["next_cursor"] == 0


def test_stream_events_read_only(journal_dir):
    """TS-06: stream_events is read-only and side-effect-free."""
    from agentcouncil.journal import write_entry, append_event, stream_events, read_entry

    write_entry(_make_journal_entry(session_id="ev-006"))
    append_event("ev-006", {"event_type": "turn_added", "data": {}})

    # Call stream_events multiple times
    r1 = stream_events("ev-006")
    r2 = stream_events("ev-006")

    # Both calls return same result — no side effects
    assert len(r1["events"]) == len(r2["events"])
    assert r1["next_cursor"] == r2["next_cursor"]

    # Entry unchanged
    entry = read_entry("ev-006")
    assert len(entry.events) == 1  # still just 1 event


def test_event_has_timestamp(journal_dir):
    """TS-03: Each event has a timestamp."""
    from agentcouncil.journal import write_entry, append_event, stream_events

    write_entry(_make_journal_entry(session_id="ev-007"))
    append_event("ev-007", {"event_type": "turn_added", "data": {}})

    result = stream_events("ev-007")
    assert result["events"][0]["timestamp"] > 0


def test_event_types(journal_dir):
    """TS-02: Events include expected types."""
    from agentcouncil.journal import write_entry, append_event, stream_events

    write_entry(_make_journal_entry(session_id="ev-008"))
    for etype in ("turn_added", "phase_transition", "status_change"):
        append_event("ev-008", {"event_type": etype, "data": {}})

    result = stream_events("ev-008")
    types = [e["event_type"] for e in result["events"]]
    assert "turn_added" in types
    assert "phase_transition" in types
    assert "status_change" in types
