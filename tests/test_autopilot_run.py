"""Tests for agentcouncil/autopilot/run.py — PERS-01 and PERS-02 behaviors.

Covers:
- PERS-01: AutopilotRun persistence (atomic writes, round-trips, path validation)
- PERS-02: Resume from paused states, failed raises, state machine enforcement
"""
from __future__ import annotations

import json
import os
import time
from typing import Any
from unittest.mock import patch

import pytest

# These imports will FAIL until run.py is created
from agentcouncil.autopilot.run import (
    AutopilotRun,
    AutopilotRunStatus,
    StageCheckpoint,
    load_run,
    persist,
    resume,
    validate_transition,
)
from agentcouncil.autopilot.artifacts import SpecPrepArtifact, SpecArtifact, CodebaseResearchBrief, ClarificationPlan


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_spec_artifact() -> SpecArtifact:
    return SpecArtifact(
        spec_id="test-spec",
        title="Test Spec",
        objective="Test objective",
        requirements=["req-1"],
        acceptance_criteria=["ac-1"],
    )


def _make_spec_prep_artifact() -> SpecPrepArtifact:
    return SpecPrepArtifact(
        prep_id="prep-1",
        finalized_spec=_make_spec_artifact(),
        research=CodebaseResearchBrief(summary="research summary"),
        clarification=ClarificationPlan(),
    )


def _make_run(**overrides: Any) -> AutopilotRun:
    """Create a minimal valid AutopilotRun for testing."""
    defaults: dict[str, Any] = {
        "run_id": "test-run-001",
        "spec_id": "test-spec",
        "status": "running",
        "current_stage": "spec_prep",
        "tier": 1,
        "stages": [
            StageCheckpoint(
                stage_name="spec_prep",
                status="in_progress",
            )
        ],
        "started_at": time.time(),
        "updated_at": time.time(),
    }
    defaults.update(overrides)
    return AutopilotRun(**defaults)


# ---------------------------------------------------------------------------
# PERS-01 tests: persistence
# ---------------------------------------------------------------------------


class TestPersistWritesValidJson:
    """test_persist_writes_valid_json: persist() writes valid JSON with required fields."""

    def test_persist_writes_valid_json(self, run_dir):
        run = _make_run()
        path = persist(run)

        assert path.exists(), "persist() must return the path to the written file"
        data = path.read_text()
        parsed = json.loads(data)

        assert parsed["run_id"] == run.run_id
        assert parsed["spec_id"] == run.spec_id
        assert "status" in parsed
        assert "stages" in parsed


class TestPersistAtomicWrite:
    """test_persist_atomic_write: if write fails mid-way, no target file left behind."""

    def test_persist_atomic_write(self, run_dir):
        run = _make_run(run_id="atomic-test")
        target = run_dir / f"{run.run_id}.json"

        # Monkeypatch os.fdopen to raise mid-write
        original_fdopen = os.fdopen

        def failing_fdopen(fd, *args, **kwargs):
            # Close the raw fd to avoid leak, then raise
            os.close(fd)
            raise OSError("simulated write failure")

        with patch("os.fdopen", side_effect=failing_fdopen):
            with pytest.raises(OSError):
                persist(run)

        # Target file must NOT exist — atomic write cleaned up
        assert not target.exists(), (
            "persist() must not leave a partial target file when write fails"
        )


class TestLoadRunRoundtrip:
    """test_load_run_roundtrip: persist then load_run recovers identical model."""

    def test_load_run_roundtrip(self, run_dir):
        run = _make_run(run_id="roundtrip-run")
        persist(run)

        loaded = load_run("roundtrip-run")
        assert loaded.model_dump() == run.model_dump()


class TestLoadRunInvalidId:
    """test_load_run_invalid_id: path traversal run_id raises ValueError with 'invalid'."""

    def test_load_run_invalid_id(self, run_dir):
        with pytest.raises(ValueError, match="invalid"):
            load_run("../etc/passwd")

    def test_load_run_empty_id(self, run_dir):
        with pytest.raises(ValueError, match="invalid"):
            load_run("")

    def test_load_run_slash_in_id(self, run_dir):
        with pytest.raises(ValueError, match="invalid"):
            load_run("sub/dir/run")


class TestLoadRunNotFound:
    """test_load_run_not_found: nonexistent run_id raises FileNotFoundError."""

    def test_load_run_not_found(self, run_dir):
        with pytest.raises(FileNotFoundError):
            load_run("nonexistent-id")


# ---------------------------------------------------------------------------
# PERS-02 tests: resume
# ---------------------------------------------------------------------------


class TestResumePausedForApproval:
    """test_resume_paused_for_approval: reconstruct artifact registry from checkpoints."""

    def test_resume_paused_for_approval(self, run_dir):
        prep = _make_spec_prep_artifact()
        snapshot = prep.model_dump()

        run = _make_run(
            run_id="resume-approval",
            status="paused_for_approval",
            stages=[
                StageCheckpoint(
                    stage_name="spec_prep",
                    status="advanced",
                    artifact_snapshot=snapshot,
                )
            ],
        )
        persist(run)

        resumed_run, registry = resume("resume-approval")

        assert resumed_run.run_id == "resume-approval"
        assert "spec_prep" in registry
        assert isinstance(registry["spec_prep"], SpecPrepArtifact), (
            "resume() must reconstruct typed SpecPrepArtifact from snapshot"
        )


class TestResumePausedForRevision:
    """test_resume_paused_for_revision: reconstruct registry AND revision_guidance accessible."""

    def test_resume_paused_for_revision(self, run_dir):
        prep = _make_spec_prep_artifact()
        snapshot = prep.model_dump()

        run = _make_run(
            run_id="resume-revision",
            status="paused_for_revision",
            stages=[
                StageCheckpoint(
                    stage_name="spec_prep",
                    status="gated",
                    artifact_snapshot=snapshot,
                    revision_guidance="Please clarify the requirements.",
                )
            ],
        )
        persist(run)

        resumed_run, registry = resume("resume-revision")

        assert "spec_prep" in registry
        assert isinstance(registry["spec_prep"], SpecPrepArtifact)
        # revision_guidance is accessible from the checkpoint
        assert resumed_run.stages[0].revision_guidance == "Please clarify the requirements."


class TestResumeFailedRaises:
    """test_resume_failed_raises: resume from failed run raises ValueError with reason."""

    def test_resume_failed_raises(self, run_dir):
        run = _make_run(
            run_id="resume-failed",
            status="failed",
            failure_reason="timeout",
        )
        persist(run)

        with pytest.raises(ValueError, match="timeout"):
            resume("resume-failed")


class TestResumeRunningRaises:
    """test_resume_running_raises: resume from running state raises ValueError."""

    def test_resume_running_raises(self, run_dir):
        run = _make_run(run_id="resume-running", status="running")
        persist(run)

        with pytest.raises(ValueError):
            resume("resume-running")


class TestResumeCompletedRaises:
    """test_resume_completed_raises: resume from completed state raises ValueError."""

    def test_resume_completed_raises(self, run_dir):
        run = _make_run(run_id="resume-completed", status="completed")
        persist(run)

        with pytest.raises(ValueError):
            resume("resume-completed")


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


class TestValidTransitions:
    """test_valid_transitions: valid transitions do not raise."""

    @pytest.mark.parametrize("from_status,to_status", [
        ("running", "paused_for_approval"),
        ("running", "paused_for_revision"),
        ("running", "completed"),
        ("running", "failed"),
    ])
    def test_valid_transition(self, from_status, to_status):
        # Must not raise
        validate_transition(from_status, to_status)


class TestInvalidTransitions:
    """test_invalid_transitions: invalid transitions raise ValueError."""

    @pytest.mark.parametrize("from_status,to_status", [
        ("paused_for_approval", "running"),
        ("paused_for_revision", "running"),
        ("completed", "running"),
        ("failed", "running"),
        ("completed", "failed"),
        ("failed", "completed"),
        ("paused_for_approval", "completed"),
    ])
    def test_invalid_transition(self, from_status, to_status):
        with pytest.raises(ValueError):
            validate_transition(from_status, to_status)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestAutopilotRunStatusEnumValues:
    """test_autopilot_run_status_enum_values: status is string not enum member."""

    def test_status_is_string(self):
        run = _make_run(status="running")
        assert isinstance(run.status, str), (
            "AutopilotRun.status must be a string (use_enum_values=True)"
        )
        assert run.status == "running"

    def test_all_status_values_are_strings(self):
        for status_val in ["running", "paused_for_approval", "paused_for_revision", "completed", "failed"]:
            run = _make_run(status=status_val)
            assert isinstance(run.status, str)
            assert run.status == status_val


class TestStageCheckpointFields:
    """test_stage_checkpoint_fields: StageCheckpoint round-trips via model_dump."""

    def test_stage_checkpoint_roundtrip(self):
        checkpoint = StageCheckpoint(
            stage_name="spec_prep",
            status="gated",
            artifact_snapshot={"key": "value"},
            gate_session_id="session-abc",
            gate_decision="advance",
            revision_guidance="Some guidance",
            started_at=1000.0,
            completed_at=2000.0,
        )
        data = checkpoint.model_dump()
        restored = StageCheckpoint(**data)

        assert restored.stage_name == "spec_prep"
        assert restored.status == "gated"
        assert restored.artifact_snapshot == {"key": "value"}
        assert restored.gate_session_id == "session-abc"
        assert restored.gate_decision == "advance"
        assert restored.revision_guidance == "Some guidance"
        assert restored.started_at == 1000.0
        assert restored.completed_at == 2000.0

    def test_stage_checkpoint_minimal(self):
        """Only required fields."""
        checkpoint = StageCheckpoint(stage_name="plan", status="pending")
        data = checkpoint.model_dump()
        assert data["stage_name"] == "plan"
        assert data["status"] == "pending"
        assert data["artifact_snapshot"] is None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    import agentcouncil.autopilot.run as rmod
    monkeypatch.setattr(rmod, "RUN_DIR", tmp_path / "autopilot")
    yield tmp_path / "autopilot"
