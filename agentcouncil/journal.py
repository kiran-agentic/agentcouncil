"""agentcouncil.journal — Deliberation Journal persistence (DJ-01 through DJ-11).

Persists session metadata, transcript turns, and final artifacts to
~/.agentcouncil/journal/ as one JSON file per session. Atomic writes
via temp file + os.replace().

Directory is created lazily on first write (DJ-10).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from agentcouncil.schemas import JournalEntry

__all__ = ["JournalEntry", "JOURNAL_DIR", "write_entry", "read_entry", "list_entries"]

log = logging.getLogger("agentcouncil.journal")

JOURNAL_DIR = Path.home() / ".agentcouncil" / "journal"


def _ensure_dir() -> None:
    """Create journal directory if it doesn't exist (DJ-10: lazy)."""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)


def write_entry(entry: JournalEntry) -> Path:
    """Persist a journal entry atomically (DJ-05, DJ-06).

    Writes to a temp file then renames to prevent partial writes on crash.

    Args:
        entry: JournalEntry to persist.

    Returns:
        Path to the written file.
    """
    _ensure_dir()
    target = JOURNAL_DIR / f"{entry.session_id}.json"
    data = entry.model_dump_json(indent=2)

    # Atomic write: temp file in same directory, then os.replace (DJ-05)
    fd, tmp_path = tempfile.mkstemp(dir=JOURNAL_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp_path, target)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    log.debug("journal entry written: %s (%d bytes)", target.name, len(data))
    return target


def read_entry(session_id: str) -> JournalEntry:
    """Read a journal entry by session_id (DJ-08).

    Args:
        session_id: UUID string identifying the session.

    Returns:
        Parsed JournalEntry.

    Raises:
        ValueError: If session_id is unknown (file not found).
    """
    target = JOURNAL_DIR / f"{session_id}.json"
    if not target.exists():
        raise ValueError(f"unknown session_id: {session_id}")

    data = target.read_text()
    return JournalEntry.model_validate_json(data)


def list_entries(
    limit: int = 20,
    protocol: Optional[str] = None,
) -> list[dict]:
    """List recent journal entries sorted by start_time descending (DJ-07).

    Returns metadata dicts (not full transcripts) for efficiency.

    Args:
        limit: Maximum number of entries to return.
        protocol: Optional protocol type filter.

    Returns:
        List of dicts with session_id, protocol_type, start_time, end_time, status.
    """
    if not JOURNAL_DIR.exists():
        return []

    entries = []
    for path in JOURNAL_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            if protocol and data.get("protocol_type") != protocol:
                continue
            entries.append({
                "session_id": data["session_id"],
                "protocol_type": data["protocol_type"],
                "start_time": data["start_time"],
                "end_time": data["end_time"],
                "status": data["status"],
                "schema_version": data.get("schema_version", "1.0"),
            })
        except (json.JSONDecodeError, KeyError):
            log.warning("skipping malformed journal entry: %s", path.name)
            continue

    # Sort by start_time descending (DJ-07)
    entries.sort(key=lambda e: e["start_time"], reverse=True)
    return entries[:limit]
