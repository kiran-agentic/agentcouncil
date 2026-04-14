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

__all__ = [
    "JournalEntry", "JOURNAL_DIR",
    "write_entry", "read_entry", "list_entries",
    "append_event", "stream_events",
]

log = logging.getLogger("agentcouncil.journal")

JOURNAL_DIR = Path.home() / ".agentcouncil" / "journal"

# R-03: session_id validation — reject path traversal attempts
_SAFE_SESSION_ID_RE = __import__("re").compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_session_id(session_id: str) -> None:
    """Reject session_ids that could escape the journal directory."""
    if not session_id or not _SAFE_SESSION_ID_RE.match(session_id):
        raise ValueError(
            f"invalid session_id: {session_id!r} — "
            "must contain only alphanumeric, hyphen, or underscore characters"
        )
    # Belt-and-suspenders: verify resolved path stays under JOURNAL_DIR
    resolved = (JOURNAL_DIR / f"{session_id}.json").resolve()
    journal_resolved = JOURNAL_DIR.resolve()
    if not str(resolved).startswith(str(journal_resolved)):
        raise ValueError(f"session_id would escape journal directory: {session_id!r}")


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
    _validate_session_id(entry.session_id)
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
    _validate_session_id(session_id)
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


# ---------------------------------------------------------------------------
# Turn Stream: append-only event log with cursor-based retrieval (TS-01..TS-09)
# ---------------------------------------------------------------------------


def append_event(session_id: str, event: dict) -> None:
    """Append an event to a journal entry's event log (TS-01, TS-09).

    Assigns a monotonic event_id and timestamp automatically.
    Uses file locking to prevent race conditions (R-04).

    Args:
        session_id: Journal session to append to.
        event: Dict with at minimum event_type and data fields.

    Raises:
        ValueError: If session_id is unknown.
    """
    import fcntl
    import time as _time

    _validate_session_id(session_id)
    target = JOURNAL_DIR / f"{session_id}.json"
    if not target.exists():
        raise ValueError(f"unknown session_id: {session_id}")

    # R-04: File lock to prevent concurrent read-modify-write races
    lock_path = JOURNAL_DIR / f"{session_id}.lock"
    _ensure_dir()
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        entry = JournalEntry.model_validate_json(target.read_text())

        next_id = len(entry.events) + 1
        event_record = {
            "event_id": next_id,
            "event_type": event.get("event_type", "unknown"),
            "timestamp": _time.time(),
            "data": event.get("data", {}),
        }
        entry.events.append(event_record)

        # Atomic write under lock
        data = entry.model_dump_json(indent=2)
        fd, tmp_path = tempfile.mkstemp(dir=JOURNAL_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def stream_events(
    session_id: str,
    since_cursor: Optional[int] = None,
) -> dict:
    """Retrieve events from a journal entry with cursor-based pagination (TS-04).

    Read-only and side-effect-free (TS-06).

    Args:
        session_id: Journal session to read from.
        since_cursor: Return events with event_id > since_cursor.
            When None, returns all events (TS-05).

    Returns:
        Dict with 'events' (list) and 'next_cursor' (int).

    Raises:
        ValueError: If session_id is unknown (TS-08).
    """
    entry = read_entry(session_id)

    if since_cursor is None:
        events = entry.events
    else:
        events = [e for e in entry.events if e.get("event_id", 0) > since_cursor]

    next_cursor = events[-1]["event_id"] if events else (since_cursor or 0)

    return {"events": events, "next_cursor": next_cursor}
