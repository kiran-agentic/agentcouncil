"""agentcouncil.workflow — Resumable Protocol State Model (RP-01 through RP-09).

Provides a protocol state machine that checkpoints at phase boundaries
and can resume from the last checkpoint.

Phase boundaries (RP-02):
    - brief_sent: after brief/input sent
    - proposals_received: after both initial proposals received
    - exchange_complete: after each exchange round
    - before_synthesis: before final synthesis
    - completed: protocol finished
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from agentcouncil.schemas import TranscriptTurn

__all__ = [
    "ProtocolPhase",
    "ProtocolCheckpoint",
    "save_checkpoint",
    "load_checkpoint",
]

log = logging.getLogger("agentcouncil.workflow")

# Type alias for checkpoint callback: fn(phase_name, data_dict) -> None
CheckpointCallback = Callable[[str, Dict[str, Any]], None]


class ProtocolPhase(str, Enum):
    """Phase boundaries where checkpointing is allowed (RP-02)."""

    brief_sent = "brief_sent"
    proposals_received = "proposals_received"
    exchange_complete = "exchange_complete"
    before_synthesis = "before_synthesis"
    completed = "completed"


class ProtocolCheckpoint(BaseModel):
    """Serializable checkpoint of protocol state at a phase boundary (RP-07)."""

    protocol_type: str
    current_phase: ProtocolPhase
    input_prompt: str
    outside_initial: Optional[str] = None
    lead_initial: Optional[str] = None
    accumulated_turns: List[TranscriptTurn] = Field(default_factory=list)
    exchange_rounds_completed: int = 0
    exchange_rounds_total: int = 1
    provider_config: dict = Field(default_factory=dict)
    artifact_cls_name: str = ""

    model_config = {"use_enum_values": True}


def save_checkpoint(session_id: str, checkpoint: ProtocolCheckpoint) -> None:
    """Persist a checkpoint to the journal entry's state field (RP-03).

    Args:
        session_id: Journal session ID to update.
        checkpoint: ProtocolCheckpoint to save.

    Raises:
        ValueError: If session_id is unknown.
    """
    from agentcouncil.journal import read_entry, write_entry

    entry = read_entry(session_id)
    entry.state = checkpoint.model_dump()
    write_entry(entry)
    log.debug("checkpoint saved: session=%s phase=%s",
              session_id, checkpoint.current_phase)


def load_checkpoint(session_id: str) -> ProtocolCheckpoint:
    """Load a checkpoint from a journal entry (RP-03).

    Args:
        session_id: Journal session ID to load from.

    Returns:
        ProtocolCheckpoint reconstructed from saved state.

    Raises:
        ValueError: If session_id is unknown, has no checkpoint,
                    or protocol is already completed (RP-05).
    """
    from agentcouncil.journal import read_entry

    entry = read_entry(session_id)

    if entry.state is None:
        raise ValueError(f"session {session_id}: no checkpoint state saved")

    checkpoint = ProtocolCheckpoint.model_validate(entry.state)

    if checkpoint.current_phase == ProtocolPhase.completed:
        raise ValueError(
            f"session {session_id}: protocol already completed — cannot resume"
        )

    log.debug("checkpoint loaded: session=%s phase=%s",
              session_id, checkpoint.current_phase)
    return checkpoint
