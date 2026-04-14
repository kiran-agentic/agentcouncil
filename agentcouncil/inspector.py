"""agentcouncil.inspector — Deliberation Inspector CLI Viewer (DI-01..DI-11).

Read-only inspection of persisted journal entries. Renders formatted
transcripts with provenance, phase markers, finding status, and
specialist evidence. Not a participation UI.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from agentcouncil.schemas import JournalEntry

__all__ = [
    "format_entry",
    "format_entry_json",
    "inspect_session",
    "inspect_list",
]

log = logging.getLogger("agentcouncil.inspector")


def _format_timestamp(ts: Optional[float]) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _phase_marker(phase: Optional[str]) -> str:
    """DI-03: Mark independence phases."""
    markers = {
        "proposal": "[PROPOSAL]",
        "exchange": "[EXCHANGE]",
        "synthesis": "[SYNTHESIS]",
        "specialist": "[SPECIALIST]",
        "convergence": "[CONVERGENCE]",
        "brief": "[BRIEF]",
    }
    return markers.get(phase or "", "")


def format_entry(entry: JournalEntry) -> str:
    """Format a journal entry for terminal display (DI-01, DI-02).

    Args:
        entry: JournalEntry to format.

    Returns:
        Formatted string with protocol type, status, turns, and provenance.
    """
    lines = []

    # Header
    lines.append(f"=== Deliberation: {entry.session_id} ===")
    lines.append(f"Protocol: {entry.protocol_type}")
    lines.append(f"Status: {entry.status}")
    lines.append(f"Started: {_format_timestamp(entry.start_time)}")
    lines.append(f"Ended: {_format_timestamp(entry.end_time)}")
    lines.append("")

    # Transcript
    transcript = entry.transcript

    if transcript.outside_initial:
        lines.append("--- Outside Initial ---")
        lines.append(transcript.outside_initial[:500])
        lines.append("")

    if transcript.lead_initial:
        lines.append("--- Lead Initial ---")
        lines.append(transcript.lead_initial[:500])
        lines.append("")

    # Exchange turns (DI-02)
    if transcript.exchanges:
        lines.append("--- Exchanges ---")
        for i, turn in enumerate(transcript.exchanges, 1):
            phase = _phase_marker(turn.phase)
            provider = f" ({turn.actor_provider})" if turn.actor_provider else ""
            model = f" [{turn.actor_model}]" if turn.actor_model else ""
            ts = f" @ {_format_timestamp(turn.timestamp)}" if turn.timestamp else ""

            lines.append(f"  Turn {i}: {turn.role}{provider}{model} {phase}{ts}")
            # Show first 200 chars of content
            content_preview = turn.content[:200]
            if len(turn.content) > 200:
                content_preview += "..."
            lines.append(f"    {content_preview}")

            # DI-05: Specialist evidence
            if turn.phase == "specialist" and turn.parent_turn_id:
                lines.append(f"    (specialist evidence for turn {turn.parent_turn_id})")
            lines.append("")

    # Synthesis (DI-06)
    if transcript.final_output:
        lines.append("--- Synthesis ---")
        lines.append(transcript.final_output[:500])
        lines.append("")

    # Artifact summary
    lines.append("--- Artifact ---")
    artifact_str = json.dumps(entry.artifact, indent=2, default=str)
    lines.append(artifact_str[:1000])

    return "\n".join(lines)


def format_entry_json(entry: JournalEntry) -> str:
    """Output raw journal JSON (DI-08).

    Args:
        entry: JournalEntry to serialize.

    Returns:
        Pretty-printed JSON string.
    """
    return entry.model_dump_json(indent=2)


def inspect_session(session_id: str) -> str:
    """Inspect a single session by ID (DI-01, DI-10).

    Args:
        session_id: UUID string of the session.

    Returns:
        Formatted string, or error message if not found (DI-10).
    """
    from agentcouncil.journal import read_entry

    try:
        entry = read_entry(session_id)
        return format_entry(entry)
    except ValueError:
        return f"Session not found: {session_id}. Use 'inspect --list' to see available sessions."


def inspect_list() -> str:
    """List recent sessions (DI-11).

    Returns:
        Formatted table of recent sessions.
    """
    from agentcouncil.journal import list_entries

    entries = list_entries(limit=20)
    if not entries:
        return "No journal entries found."

    lines = ["Session ID                            | Protocol    | Status      | Started"]
    lines.append("-" * 85)

    for e in entries:
        sid = e["session_id"][:36]
        proto = e["protocol_type"].ljust(11)
        status = str(e["status"]).ljust(11)
        started = _format_timestamp(e["start_time"])
        lines.append(f"{sid} | {proto} | {status} | {started}")

    return "\n".join(lines)


def main():
    """CLI entry point for agentcouncil inspect."""
    import sys

    args = sys.argv[1:]

    if not args or args[0] == "--help":
        print("Usage: agentcouncil inspect <session_id> [--json] [--list]")
        return

    if args[0] == "--list" or args[0] == "list":
        print(inspect_list())
        return

    session_id = args[0]

    if "--json" in args:
        from agentcouncil.journal import read_entry
        try:
            entry = read_entry(session_id)
            print(format_entry_json(entry))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(inspect_session(session_id))
