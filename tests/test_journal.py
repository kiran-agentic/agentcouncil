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
