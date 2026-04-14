"""Tests for Resumable Protocol State Model (RP-01 through RP-09)."""
from __future__ import annotations

import pytest

from agentcouncil.schemas import ConsensusStatus, Transcript


# ---------------------------------------------------------------------------
# RP-01, RP-07: ProtocolCheckpoint model
# ---------------------------------------------------------------------------


def test_protocol_checkpoint_model():
    """RP-01, RP-07: ProtocolCheckpoint has required fields."""
    from agentcouncil.workflow import ProtocolCheckpoint, ProtocolPhase

    cp = ProtocolCheckpoint(
        protocol_type="review",
        current_phase=ProtocolPhase.proposals_received,
        input_prompt="review this code",
        outside_initial="findings...",
        lead_initial="my review...",
        exchange_rounds_completed=0,
        exchange_rounds_total=1,
        provider_config={"profile": "codex"},
        artifact_cls_name="ReviewArtifact",
    )
    assert cp.protocol_type == "review"
    assert cp.current_phase == ProtocolPhase.proposals_received
    assert cp.input_prompt == "review this code"
    assert cp.provider_config == {"profile": "codex"}


def test_protocol_phase_enum():
    """RP-02: ProtocolPhase has all defined phase boundaries."""
    from agentcouncil.workflow import ProtocolPhase

    expected = {"brief_sent", "proposals_received", "exchange_complete",
                "before_synthesis", "completed"}
    assert set(p.value for p in ProtocolPhase) == expected


# ---------------------------------------------------------------------------
# RP-02: Checkpoint at phase boundaries
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_dir(tmp_path):
    """Provide a temp directory for journal tests."""
    import agentcouncil.journal as jmod
    original = jmod.JOURNAL_DIR
    jmod.JOURNAL_DIR = tmp_path / "journal"
    yield tmp_path / "journal"
    jmod.JOURNAL_DIR = original


def test_checkpoint_save_and_load(journal_dir):
    """RP-03: Checkpoints are persisted via Journal and loadable."""
    from agentcouncil.workflow import (
        ProtocolCheckpoint, ProtocolPhase,
        save_checkpoint, load_checkpoint,
    )
    from agentcouncil.journal import write_entry
    from agentcouncil.schemas import JournalEntry, Transcript

    # First create a journal entry to attach checkpoint to
    entry = JournalEntry(
        session_id="cp-test-001",
        protocol_type="review",
        start_time=100.0,
        end_time=0.0,
        status=ConsensusStatus.consensus,
        artifact={},
        transcript=Transcript(input_prompt="test"),
    )
    write_entry(entry)

    # Save a checkpoint
    cp = ProtocolCheckpoint(
        protocol_type="review",
        current_phase=ProtocolPhase.proposals_received,
        input_prompt="review this",
        outside_initial="outside says...",
        lead_initial="lead says...",
        exchange_rounds_completed=0,
        exchange_rounds_total=1,
        provider_config={"profile": "codex"},
        artifact_cls_name="ReviewArtifact",
    )
    save_checkpoint("cp-test-001", cp)

    # Load it back
    loaded = load_checkpoint("cp-test-001")
    assert loaded.protocol_type == "review"
    assert loaded.current_phase == ProtocolPhase.proposals_received
    assert loaded.outside_initial == "outside says..."
    assert loaded.provider_config == {"profile": "codex"}


def test_load_checkpoint_completed_raises(journal_dir):
    """RP-05: Loading checkpoint from completed protocol raises ValueError."""
    from agentcouncil.workflow import (
        ProtocolCheckpoint, ProtocolPhase,
        save_checkpoint, load_checkpoint,
    )
    from agentcouncil.journal import write_entry
    from agentcouncil.schemas import JournalEntry, Transcript

    entry = JournalEntry(
        session_id="cp-done-001",
        protocol_type="review",
        start_time=100.0,
        end_time=200.0,
        status=ConsensusStatus.consensus,
        artifact={},
        transcript=Transcript(input_prompt="test"),
    )
    write_entry(entry)

    cp = ProtocolCheckpoint(
        protocol_type="review",
        current_phase=ProtocolPhase.completed,
        input_prompt="test",
        exchange_rounds_completed=0,
        exchange_rounds_total=1,
        provider_config={},
        artifact_cls_name="ReviewArtifact",
    )
    save_checkpoint("cp-done-001", cp)

    with pytest.raises(ValueError, match="completed"):
        load_checkpoint("cp-done-001")


def test_load_checkpoint_unknown_session_raises(journal_dir):
    """RP-05: Loading checkpoint from unknown session raises ValueError."""
    from agentcouncil.workflow import load_checkpoint

    # Ensure dir exists
    journal_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError):
        load_checkpoint("nonexistent-session")


def test_load_checkpoint_no_state_raises(journal_dir):
    """Loading checkpoint from entry with no state field raises ValueError."""
    from agentcouncil.workflow import load_checkpoint
    from agentcouncil.journal import write_entry
    from agentcouncil.schemas import JournalEntry, Transcript

    entry = JournalEntry(
        session_id="no-state-001",
        protocol_type="review",
        start_time=100.0,
        end_time=200.0,
        status=ConsensusStatus.consensus,
        artifact={},
        transcript=Transcript(input_prompt="test"),
    )
    write_entry(entry)

    with pytest.raises(ValueError, match="no checkpoint"):
        load_checkpoint("no-state-001")


# ---------------------------------------------------------------------------
# RP-08: No mid-turn checkpointing
# ---------------------------------------------------------------------------


def test_checkpoint_serialization_roundtrip():
    """RP-07: ProtocolCheckpoint survives JSON serialization roundtrip."""
    from agentcouncil.workflow import ProtocolCheckpoint, ProtocolPhase

    cp = ProtocolCheckpoint(
        protocol_type="review",
        current_phase=ProtocolPhase.exchange_complete,
        input_prompt="review this",
        outside_initial="outside",
        lead_initial="lead",
        exchange_rounds_completed=1,
        exchange_rounds_total=2,
        provider_config={"profile": "codex", "model": "gpt-4.1"},
        artifact_cls_name="ReviewArtifact",
    )
    json_str = cp.model_dump_json()
    restored = ProtocolCheckpoint.model_validate_json(json_str)
    assert restored.model_dump() == cp.model_dump()


# ---------------------------------------------------------------------------
# RP-02: checkpoint_callback in run_deliberation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_deliberation_checkpoint_callback():
    """RP-02: run_deliberation calls checkpoint_callback at phase boundaries."""
    import json
    from agentcouncil.deliberation import run_deliberation
    from agentcouncil.adapters import StubAdapter
    from agentcouncil.schemas import ReviewArtifact
    from agentcouncil.review import _review_synthesis_prompt_fn

    review_json = json.dumps({
        "verdict": "pass",
        "summary": "Looks good",
        "findings": [],
        "strengths": ["Clean code"],
        "open_questions": [],
        "next_action": "Ship it",
    })

    outside = StubAdapter(["Outside review", review_json])
    lead = StubAdapter(["Lead review"])

    checkpoints = []

    def on_checkpoint(phase, data):
        checkpoints.append((phase, data))

    result = await run_deliberation(
        input_prompt="Review this code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_review_synthesis_prompt_fn,
        exchange_rounds=1,
        checkpoint_callback=on_checkpoint,
    )

    assert result.artifact.verdict == "pass"
    # Should have checkpoints: after outside_initial, after lead_initial, before synthesis
    assert len(checkpoints) >= 2
    phases = [cp[0] for cp in checkpoints]
    assert "proposals_received" in phases


# ---------------------------------------------------------------------------
# RP-04, RP-05, RP-09: Resume tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_protocol_from_checkpoint(journal_dir):
    """RP-04, RP-09: resume_protocol reconstructs state and completes with same artifact type."""
    import json
    from agentcouncil.workflow import (
        ProtocolCheckpoint, ProtocolPhase,
        save_checkpoint, resume_protocol,
    )
    from agentcouncil.journal import write_entry
    from agentcouncil.schemas import JournalEntry, Transcript, ReviewArtifact
    from agentcouncil.adapters import StubAdapter

    review_json = json.dumps({
        "verdict": "pass",
        "summary": "Looks good",
        "findings": [],
        "strengths": ["Clean"],
        "open_questions": [],
        "next_action": "Ship",
    })

    # Create a journal entry with a checkpoint at proposals_received
    entry = JournalEntry(
        session_id="resume-001",
        protocol_type="review",
        start_time=100.0,
        end_time=0.0,
        status="consensus",
        artifact={},
        transcript=Transcript(input_prompt="Review this code"),
    )
    write_entry(entry)

    cp = ProtocolCheckpoint(
        protocol_type="review",
        current_phase=ProtocolPhase.before_synthesis,
        input_prompt="Review this code",
        outside_initial="Outside: looks risky",
        lead_initial="Lead: seems fine",
        exchange_rounds_completed=0,
        exchange_rounds_total=1,
        provider_config={"profile": "stub"},
        artifact_cls_name="ReviewArtifact",
    )
    save_checkpoint("resume-001", cp)

    # Resume with a stub adapter that provides synthesis
    outside = StubAdapter([review_json])
    lead = StubAdapter([])

    result = await resume_protocol("resume-001", outside, lead)

    # RP-09: same artifact type as non-resumed run
    assert isinstance(result.artifact, ReviewArtifact)
    assert result.artifact.verdict == "pass"


@pytest.mark.asyncio
async def test_resume_completed_protocol_raises(journal_dir):
    """RP-05: resume on completed protocol raises ValueError."""
    from agentcouncil.workflow import (
        ProtocolCheckpoint, ProtocolPhase,
        save_checkpoint, resume_protocol,
    )
    from agentcouncil.journal import write_entry
    from agentcouncil.schemas import JournalEntry, Transcript
    from agentcouncil.adapters import StubAdapter

    entry = JournalEntry(
        session_id="done-001",
        protocol_type="review",
        start_time=100.0,
        end_time=200.0,
        status="consensus",
        artifact={},
        transcript=Transcript(input_prompt="test"),
    )
    write_entry(entry)

    cp = ProtocolCheckpoint(
        protocol_type="review",
        current_phase=ProtocolPhase.completed,
        input_prompt="test",
        exchange_rounds_completed=0,
        exchange_rounds_total=1,
        provider_config={},
        artifact_cls_name="ReviewArtifact",
    )
    save_checkpoint("done-001", cp)

    with pytest.raises(ValueError, match="completed"):
        await resume_protocol("done-001", StubAdapter([]), StubAdapter([]))
