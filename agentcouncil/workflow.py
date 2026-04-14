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
    "resume_protocol",
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


async def resume_protocol(
    session_id: str,
    outside_adapter: Any,
    lead_adapter: Any,
) -> Any:
    """Resume a protocol from its last checkpoint (RP-04, RP-09).

    Reconstructs protocol state from the journal checkpoint and continues
    execution from the interrupted phase. Returns the same artifact type
    as a non-resumed run (RP-09).

    Args:
        session_id: Journal session ID with saved checkpoint.
        outside_adapter: AgentAdapter for the outside agent.
        lead_adapter: AgentAdapter for the lead agent.

    Returns:
        DeliberationResult with the protocol-specific artifact.

    Raises:
        ValueError: If session is unknown, has no checkpoint, or is completed (RP-05).
    """
    checkpoint = load_checkpoint(session_id)

    # Resolve artifact class from name
    from agentcouncil.schemas import ReviewArtifact, DecideArtifact, ChallengeArtifact
    artifact_cls_map = {
        "ReviewArtifact": ReviewArtifact,
        "DecideArtifact": DecideArtifact,
        "ChallengeArtifact": ChallengeArtifact,
    }
    artifact_cls = artifact_cls_map.get(checkpoint.artifact_cls_name)
    if artifact_cls is None:
        raise ValueError(f"unknown artifact class: {checkpoint.artifact_cls_name}")

    # Resolve synthesis prompt function from protocol type
    if checkpoint.protocol_type == "review":
        from agentcouncil.review import _review_synthesis_prompt_fn, _review_derive_status
        synthesis_fn = _review_synthesis_prompt_fn
        derive_status = _review_derive_status
    elif checkpoint.protocol_type == "decide":
        from agentcouncil.decide import _decide_synthesis_prompt_fn, _decide_derive_status
        synthesis_fn = _decide_synthesis_prompt_fn
        derive_status = _decide_derive_status
    elif checkpoint.protocol_type == "challenge":
        from agentcouncil.challenge import _challenge_synthesis_prompt_fn, _challenge_derive_status
        synthesis_fn = _challenge_synthesis_prompt_fn
        derive_status = _challenge_derive_status
    else:
        raise ValueError(f"resume not supported for protocol: {checkpoint.protocol_type}")

    # R-01: Build resume_state from checkpoint to inject into run_deliberation
    from agentcouncil.deliberation import run_deliberation

    resume_state: dict[str, Any] = {
        "outside_initial": checkpoint.outside_initial,
        "lead_initial": checkpoint.lead_initial,
        "exchanges": [t.model_dump() for t in checkpoint.accumulated_turns],
    }

    if checkpoint.current_phase == ProtocolPhase.before_synthesis:
        # Only synthesis remains — skip proposals and exchanges
        resume_state["skip_to"] = "synthesis"
        return await run_deliberation(
            input_prompt=checkpoint.input_prompt,
            outside_adapter=outside_adapter,
            lead_adapter=lead_adapter,
            artifact_cls=artifact_cls,
            synthesis_prompt_fn=synthesis_fn,
            exchange_rounds=1,
            derive_status=derive_status,
            resume_state=resume_state,
        )

    if checkpoint.current_phase == ProtocolPhase.proposals_received:
        # Proposals done, may need exchanges + synthesis
        resume_state["skip_to"] = "exchanges"
        remaining_rounds = checkpoint.exchange_rounds_total - checkpoint.exchange_rounds_completed
        return await run_deliberation(
            input_prompt=checkpoint.input_prompt,
            outside_adapter=outside_adapter,
            lead_adapter=lead_adapter,
            artifact_cls=artifact_cls,
            synthesis_prompt_fn=synthesis_fn,
            exchange_rounds=max(1, remaining_rounds),
            derive_status=derive_status,
            resume_state=resume_state,
        )

    # For earlier phases (brief_sent), restart from beginning
    return await run_deliberation(
        input_prompt=checkpoint.input_prompt,
        outside_adapter=outside_adapter,
        lead_adapter=lead_adapter,
        artifact_cls=artifact_cls,
        synthesis_prompt_fn=synthesis_fn,
        exchange_rounds=max(1, checkpoint.exchange_rounds_total),
        derive_status=derive_status,
    )
