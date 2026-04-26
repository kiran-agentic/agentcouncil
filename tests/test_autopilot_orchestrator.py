"""Tests for agentcouncil/autopilot/orchestrator.py — ORCH-03 and ORCH-05 behaviors.

Covers:
- ORCH-03: LinearOrchestrator sequences work stages through the full pipeline
  with gate loop (advance / revise / block) and persist at every checkpoint.
- ORCH-05: Challenge gate fires conditionally after verify (side_effect_level=external
  or tier=3); skipped for tier=2 with non-external side effects.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

# These imports will FAIL until orchestrator.py is created (RED phase)
from agentcouncil.autopilot.orchestrator import LinearOrchestrator, StageRunner
from agentcouncil.autopilot.run import (
    AutopilotRun,
    StageCheckpoint,
    load_run,
    persist,
    resume,
    validate_transition,
)
from agentcouncil.autopilot.loader import (
    StageRegistryEntry,
    StageManifest,
    load_default_registry,
)
from agentcouncil.autopilot.artifacts import (
    AcceptanceProbe,
    BuildArtifact,
    BuildEvidence,
    ClarificationPlan,
    CodebaseResearchBrief,
    CriterionVerification,
    GateDecision,
    PlanArtifact,
    PlanTask,
    ShipArtifact,
    SpecArtifact,
    SpecPrepArtifact,
    VerificationEnvironment,
    VerifyArtifact,
    CommandEvidence,
)


# ---------------------------------------------------------------------------
# Stub artifact factories
# ---------------------------------------------------------------------------


def _stub_spec_prep_artifact() -> SpecPrepArtifact:
    return SpecPrepArtifact(
        prep_id="prep-1",
        finalized_spec=SpecArtifact(
            spec_id="test-spec",
            title="Test",
            objective="Test obj",
            requirements=["r1"],
            acceptance_criteria=["ac-1"],
        ),
        research=CodebaseResearchBrief(summary="stub"),
        clarification=ClarificationPlan(),
    )


def _stub_plan_artifact() -> PlanArtifact:
    return PlanArtifact(
        plan_id="plan-1",
        spec_id="test-spec",
        tasks=[
            PlanTask(
                task_id="t1",
                title="Task 1",
                description="d",
                acceptance_criteria=["ac-1"],
                target_files=["f.py"],
            )
        ],
        acceptance_probes=[
            AcceptanceProbe(
                probe_id="p-1",
                criterion_id="ac-0",
                criterion_text="c",
                verification_level="unit",
                target_behavior="test behavior",
                expected_observation="pass",
            )
        ],
        execution_order=["t1"],
        verification_strategy="run pytest",
    )


def _stub_build_artifact() -> BuildArtifact:
    return BuildArtifact(
        build_id="build-1",
        plan_id="plan-1",
        spec_id="test-spec",
        evidence=[
            BuildEvidence(
                task_id="t1",
                files_changed=["f.py"],
                verification_notes="built",
            )
        ],
        all_tests_passing=True,
        files_changed=["f.py"],
    )


def _stub_verify_artifact() -> VerifyArtifact:
    return VerifyArtifact(
        verify_id="verify-1",
        build_id="build-1",
        plan_id="plan-1",
        spec_id="test-spec",
        test_environment=VerificationEnvironment(),
        criteria_verdicts=[
            CriterionVerification(
                criterion_id="ac-0",
                criterion_text="c",
                status="passed",
                verification_level="unit",
                mock_policy="not_applicable",
                evidence_summary="ok",
            )
        ],
        overall_status="passed",
    )


def _stub_ship_artifact() -> ShipArtifact:
    return ShipArtifact(
        ship_id="ship-1",
        verify_id="verify-1",
        build_id="build-1",
        plan_id="plan-1",
        spec_id="test-spec",
        branch_name="main",
        head_sha="abc123",
        worktree_clean=True,
        tests_passing=True,
        acceptance_criteria_met=True,
        readiness_summary="ready",
        release_notes="done",
        rollback_plan="revert commit",
        recommended_action="ship",
    )


# ---------------------------------------------------------------------------
# Test registry and runner helpers
# ---------------------------------------------------------------------------


def _make_test_registry() -> dict[str, StageRegistryEntry]:
    """Return the real default stage registry."""
    return load_default_registry()


def _make_stub_runners() -> dict[str, StageRunner]:
    """Return stub runners for all 5 stages."""
    factories = {
        "spec_prep": _stub_spec_prep_artifact,
        "plan": _stub_plan_artifact,
        "build": _stub_build_artifact,
        "verify": _stub_verify_artifact,
        "ship": _stub_ship_artifact,
    }

    def _make_runner(stage_name):
        def runner(run: AutopilotRun, registry: dict, guidance: Optional[str] = None):
            return factories[stage_name]()
        return runner

    return {name: _make_runner(name) for name in factories}


def _make_run(
    run_id: str = "test-run-001",
    tier: int = 2,
    current_stage: str = "spec_prep",
) -> AutopilotRun:
    """Create a minimal valid AutopilotRun for testing."""
    stages = [
        StageCheckpoint(stage_name=name, status="pending")
        for name in ["spec_prep", "plan", "build", "verify", "ship"]
    ]
    return AutopilotRun(
        run_id=run_id,
        spec_id="test-spec",
        status="running",
        current_stage=current_stage,
        tier=tier,
        stages=stages,
        started_at=time.time(),
        updated_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Revise-once gate helper
# ---------------------------------------------------------------------------


class _ReviseOnceGate:
    """Gate stub that returns revise on first call, advance on second call."""

    def __init__(self):
        self.call_count = 0

    def __call__(self) -> GateDecision:
        self.call_count += 1
        if self.call_count == 1:
            return GateDecision(
                decision="revise",
                protocol_type="review_loop",
                protocol_session_id="stub",
                rationale="revise",
                revision_guidance="fix this",
            )
        return GateDecision(
            decision="advance",
            protocol_type="review_loop",
            protocol_session_id="stub",
            rationale="ok",
        )


class _AdvanceGate:
    """Gate stub that always returns advance."""

    def __call__(self) -> GateDecision:
        return GateDecision(
            decision="advance",
            protocol_type="review_loop",
            protocol_session_id="stub",
            rationale="ok",
        )


class _BlockGate:
    """Gate stub that always returns block."""

    def __call__(self) -> GateDecision:
        return GateDecision(
            decision="block",
            protocol_type="review_loop",
            protocol_session_id="stub",
            rationale="blocked",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """Redirect RUN_DIR to a temp path for test isolation."""
    import agentcouncil.autopilot.run as rmod
    monkeypatch.setattr(rmod, "RUN_DIR", tmp_path / "autopilot")
    yield tmp_path / "autopilot"


# ---------------------------------------------------------------------------
# TestEndToEnd — ORCH-03 happy path
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """test_happy_path_reaches_completed: full pipeline with stub stages completes."""

    def test_happy_path_reaches_completed(self, run_dir):
        """An end-to-end run with stub stages reaches status=completed."""
        registry = _make_test_registry()
        runners = _make_stub_runners()
        # Use advance gate runners so all stages advance immediately
        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="e2e-run", tier=2)

        result = orchestrator.run_pipeline(run)

        assert result.status == "completed", (
            f"Expected status=completed, got {result.status!r}"
        )
        # Verify all work stages advanced
        for checkpoint in result.stages:
            assert checkpoint.status in ("advanced", "skipped"), (
                f"Stage {checkpoint.stage_name!r} has status={checkpoint.status!r}"
            )

    def test_happy_path_run_persisted(self, run_dir):
        """After completing, the run file must exist on disk."""
        registry = _make_test_registry()
        runners = _make_stub_runners()
        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="e2e-persist-run", tier=2)

        result = orchestrator.run_pipeline(run)

        loaded = load_run("e2e-persist-run")
        assert loaded.status == "completed"


# ---------------------------------------------------------------------------
# TestReviseLoop — ORCH-03 revise behavior
# ---------------------------------------------------------------------------


class TestReviseLoop:
    """test_revise_then_advance: revise gate causes re-execution with revision_guidance."""

    def test_revise_then_advance(self, run_dir):
        """A gate that returns revise then advance causes work stage to run twice."""
        registry = _make_test_registry()

        # Track calls and revision_guidance passed to the plan runner
        call_args = []

        def tracking_plan_runner(run: AutopilotRun, reg: dict, guidance: Optional[str] = None):
            call_args.append(guidance)
            return _stub_plan_artifact()

        runners = _make_stub_runners()
        runners["plan"] = tracking_plan_runner

        revise_gate = _ReviseOnceGate()
        gate_runners = {
            "review_loop": revise_gate,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="revise-run", tier=2)

        result = orchestrator.run_pipeline(run)

        # Work stage called twice (initial + after revise)
        # plan has review_loop gate, so call_args has plan calls
        assert len(call_args) == 2, (
            f"Expected plan runner called twice, got {len(call_args)} calls"
        )
        # First call has no guidance, second has guidance from gate
        assert call_args[0] is None
        assert call_args[1] == "fix this", (
            f"Expected revision_guidance='fix this', got {call_args[1]!r}"
        )

    def test_revise_gate_call_count(self, run_dir):
        """The revise-once gate must be called exactly twice (revise, then advance)."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        revise_gate = _ReviseOnceGate()
        gate_runners = {
            "review_loop": revise_gate,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="revise-count-run", tier=2)
        orchestrator.run_pipeline(run)

        # review_loop gate runs for plan and build (both have review_loop)
        # plan: revise once then advance = 2 calls
        # build: should advance on first call (revise_gate.call_count resets)
        # Actually _ReviseOnceGate doesn't reset — call 3 onwards returns advance
        assert revise_gate.call_count >= 2


# ---------------------------------------------------------------------------
# TestBlockHalt — ORCH-03 block behavior
# ---------------------------------------------------------------------------


class TestBlockHalt:
    """test_block_sets_paused: block gate decision halts with paused_for_approval."""

    def test_block_sets_paused(self, run_dir):
        """A gate that always returns block halts with status=paused_for_approval."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        gate_runners = {
            "review_loop": _BlockGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="block-run", tier=2)

        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval, got {result.status!r}"
        )

    def test_block_run_persisted(self, run_dir):
        """After blocking, the run must be persisted with paused_for_approval status."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        gate_runners = {
            "review_loop": _BlockGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="block-persist-run", tier=2)

        orchestrator.run_pipeline(run)

        loaded = load_run("block-persist-run")
        assert loaded.status == "paused_for_approval", (
            "Blocked run must be persisted with paused_for_approval status"
        )

    def test_block_stage_checkpoint_status(self, run_dir):
        """The blocked stage checkpoint must have status=blocked."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        gate_runners = {
            "review_loop": _BlockGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="block-checkpoint-run", tier=2)

        result = orchestrator.run_pipeline(run)

        # plan is first stage with review_loop gate — should be blocked
        plan_checkpoint = next(
            (c for c in result.stages if c.stage_name == "plan"), None
        )
        assert plan_checkpoint is not None
        assert plan_checkpoint.status == "blocked", (
            f"Expected plan checkpoint status=blocked, got {plan_checkpoint.status!r}"
        )


# ---------------------------------------------------------------------------
# TestResume — ORCH-03 resume behavior
# ---------------------------------------------------------------------------


class TestResume:
    """test_resume_continues_from_blocked: resume continues pipeline from blocked stage."""

    def test_resume_continues_from_blocked(self, run_dir):
        """Block at plan stage, then resume and complete from plan."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        # First: block at plan
        gate_runners = {
            "review_loop": _BlockGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="resume-test-run", tier=2)
        blocked_run = orchestrator.run_pipeline(run)
        assert blocked_run.status == "paused_for_approval"

        # Now resume: create new orchestrator with advance gates
        gate_runners_advance = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator2 = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners_advance,
        )

        # Resume: load run and set status back to running at the blocked stage
        resumed_run, artifact_registry = resume("resume-test-run")
        # Reset run status to running for re-execution
        # (orchestrator responsible for handling this in run_pipeline)
        resumed_run.status = "running"  # type: ignore[assignment]
        result = orchestrator2.run_pipeline(resumed_run, artifact_registry)

        assert result.status == "completed", (
            f"Expected resumed run to complete, got {result.status!r}"
        )

    def test_resume_run_persisted_on_completion(self, run_dir):
        """After resuming and completing, the run file has status=completed."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        # First block
        gate_runners = {
            "review_loop": _BlockGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry, runners=runners, gate_runners=gate_runners
        )
        run = _make_run(run_id="resume-persist-run", tier=2)
        orchestrator.run_pipeline(run)

        # Then resume and complete
        gate_runners_advance = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator2 = LinearOrchestrator(
            registry=registry, runners=runners, gate_runners=gate_runners_advance
        )
        resumed_run, artifact_registry = resume("resume-persist-run")
        resumed_run.status = "running"  # type: ignore[assignment]
        orchestrator2.run_pipeline(resumed_run, artifact_registry)

        loaded = load_run("resume-persist-run")
        assert loaded.status == "completed"


# ---------------------------------------------------------------------------
# TestChallengeGate — ORCH-05 conditional challenge gate
# ---------------------------------------------------------------------------


def _make_external_verify_registry() -> dict[str, StageRegistryEntry]:
    """Return a modified registry where verify has side_effect_level=external."""
    registry = load_default_registry()
    verify_entry = registry["verify"]
    # Build a new manifest with side_effect_level=external
    raw = verify_entry.manifest.model_dump()
    raw["side_effect_level"] = "external"
    new_manifest = StageManifest(**raw)
    registry["verify"] = StageRegistryEntry(
        manifest=new_manifest,
        workflow_content=verify_entry.workflow_content,
    )
    return registry


class TestChallengeGate:
    """Tests for ORCH-05: conditional challenge gate after verify."""

    def test_challenge_fires_for_external(self, run_dir):
        """Challenge gate is invoked after verify when side_effect_level=external.

        With SAFE-02, external stages require pre-execution approval. This test simulates
        the resume-after-approval scenario: verify's checkpoint is pre-set to 'blocked'
        (approval granted), so the approval guard bypasses and the challenge gate fires.
        """
        registry = _make_external_verify_registry()
        runners = _make_stub_runners()

        class TrackingChallengeGate:
            def __init__(self):
                self.called = False

            def __call__(self) -> GateDecision:
                self.called = True
                return GateDecision(
                    decision="advance",
                    protocol_type="challenge",
                    protocol_session_id="stub",
                    rationale="challenge passed",
                )

        tracking_gate = TrackingChallengeGate()
        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": tracking_gate,
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # Start from verify stage with verify checkpoint already "blocked" (approval granted).
        # This simulates the resume-after-approval flow: the pipeline paused at verify
        # for approval, human approved, run.status was reset to running and run_pipeline called.
        run = _make_run(run_id="challenge-external-run", tier=2, current_stage="verify")
        # Pre-populate prior stage artifacts so artifact_registry is consistent
        artifact_registry = {
            "spec_prep": _stub_spec_prep_artifact(),
            "plan": _stub_plan_artifact(),
            "build": _stub_build_artifact(),
        }
        # Mark earlier stages as advanced in checkpoints
        for checkpoint in run.stages:
            if checkpoint.stage_name in ("spec_prep", "plan", "build"):
                checkpoint.status = "advanced"
        # Pre-set verify checkpoint to "blocked" — simulates approval already granted
        verify_cp = next(c for c in run.stages if c.stage_name == "verify")
        verify_cp.status = "blocked"

        result = orchestrator.run_pipeline(run, artifact_registry=artifact_registry)

        assert tracking_gate.called, (
            "Challenge gate must be invoked for side_effect_level=external"
        )
        assert result.status == "completed"

    def test_challenge_fires_for_tier3(self, run_dir):
        """Challenge gate fires after verify when tier=3, regardless of side_effect_level."""
        registry = _make_test_registry()  # verify has side_effect_level=local
        runners = _make_stub_runners()

        class TrackingChallengeGate:
            def __init__(self):
                self.called = False

            def __call__(self) -> GateDecision:
                self.called = True
                return GateDecision(
                    decision="advance",
                    protocol_type="challenge",
                    protocol_session_id="stub",
                    rationale="tier3 challenge passed",
                )

        tracking_gate = TrackingChallengeGate()
        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": tracking_gate,
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # tier=3 should trigger challenge even with local side_effect_level
        run = _make_run(run_id="challenge-tier3-run", tier=3)
        result = orchestrator.run_pipeline(run)

        assert tracking_gate.called, (
            "Challenge gate must be invoked for tier=3"
        )
        assert result.status == "completed"

    def test_challenge_skipped_for_tier2(self, run_dir):
        """Challenge gate is NOT invoked for tier=2 with side_effect_level=local."""
        registry = _make_test_registry()  # verify has side_effect_level=local

        # Sanity check: the default manifest has side_effect_level=local for verify
        assert registry["verify"].manifest.side_effect_level == "local"

        runners = _make_stub_runners()

        class TrackingChallengeGate:
            def __init__(self):
                self.called = False

            def __call__(self) -> GateDecision:
                self.called = True
                return GateDecision(
                    decision="advance",
                    protocol_type="challenge",
                    protocol_session_id="stub",
                    rationale="should not be called",
                )

        tracking_gate = TrackingChallengeGate()
        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": tracking_gate,
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # tier=2 with local side_effect_level — no challenge gate
        run = _make_run(run_id="challenge-skip-run", tier=2)
        result = orchestrator.run_pipeline(run)

        assert not tracking_gate.called, (
            "Challenge gate must NOT be invoked for tier=2 with side_effect_level=local"
        )
        assert result.status == "completed"

    def test_challenge_skipped_default_gate_none_stage(self, run_dir):
        """Stages with default_gate=none skip the gate entirely (spec_prep, ship)."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        # spec_prep and ship have gate=none — gate_runners should not be called
        none_gate_calls = []

        class TrackingNoneGate:
            def __call__(self) -> GateDecision:
                none_gate_calls.append("none")
                return GateDecision(
                    decision="advance",
                    protocol_type="review_loop",
                    protocol_session_id="stub",
                    rationale="ok",
                )

        gate_runners = {
            "none": TrackingNoneGate(),
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="none-gate-run", tier=2)
        result = orchestrator.run_pipeline(run)

        assert none_gate_calls == [], (
            "gate_runners['none'] must never be called for default_gate=none stages"
        )
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# TestMCPTools — PERS-04: MCP tool registration and basic behavior
# ---------------------------------------------------------------------------


class TestMCPTools:
    """PERS-04: MCP tool registration and basic behavior."""

    def test_prepare_returns_run_id(self, tmp_path, monkeypatch):
        """autopilot_prepare creates a run and returns run_id."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path)
        from agentcouncil.server import autopilot_prepare_tool
        result = autopilot_prepare_tool(
            intent="test", spec_id="s1", title="T", objective="O",
            requirements=["r1"], acceptance_criteria=["ac1"], tier=2,
        )
        assert "run_id" in result
        assert result["status"] == "running"
        assert result["current_stage"] == "spec_prep"
        # Verify file was persisted
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1

    def test_prepare_persists_gate_backends(self, tmp_path, monkeypatch):
        """autopilot_prepare stores review/challenge backend choices."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path)
        from agentcouncil.server import autopilot_prepare_tool, autopilot_status_tool

        prep = autopilot_prepare_tool(
            intent="test", spec_id="s1", title="T", objective="O",
            requirements=["r1"], acceptance_criteria=["ac1"],
            review_backend="openrouter-gpt",
            challenge_backend="bedrock-sonnet",
        )

        assert prep["review_backend"] == "openrouter-gpt"
        assert prep["challenge_backend"] == "bedrock-sonnet"

        status = autopilot_status_tool(run_id=prep["run_id"])
        assert status["review_backend"] == "openrouter-gpt"
        assert status["challenge_backend"] == "bedrock-sonnet"

    def test_status_reflects_run(self, tmp_path, monkeypatch):
        """autopilot_status returns current run state."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path)
        from agentcouncil.server import autopilot_prepare_tool, autopilot_status_tool
        prep = autopilot_prepare_tool(
            intent="test", spec_id="s1", title="T", objective="O",
            requirements=["r1"], acceptance_criteria=["ac1"],
        )
        status = autopilot_status_tool(run_id=prep["run_id"])
        assert status["run_id"] == prep["run_id"]
        assert status["status"] == "running"
        assert status["protocol_step"] == "spec_prep_started"
        assert status["required_tool"] == "autopilot_checkpoint"
        assert "resume_prompt" in status
        assert len(status["stages"]) == 5

    def test_checkpoint_tool_records_guard_state(self, tmp_path, monkeypatch):
        """autopilot_checkpoint returns guard payload and writes project-local state."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path / "runs")
        from agentcouncil.server import (
            autopilot_checkpoint_tool,
            autopilot_prepare_tool,
            autopilot_status_tool,
        )
        prep = autopilot_prepare_tool(
            intent="test", spec_id="s1", title="T", objective="O",
            requirements=["r1"], acceptance_criteria=["ac1"],
        )

        checkpoint = autopilot_checkpoint_tool(
            run_id=prep["run_id"],
            protocol_step="awaiting_build_review",
            next_required_action="Run the build review gate.",
            required_tool="review_loop",
            artifact_refs={"build": "docs/autopilot/runs/build-artifact.json"},
            stage="build",
            stage_status="gated",
            workspace_path=str(tmp_path),
            review_backend="codex",
            challenge_backend="claude",
        )

        assert checkpoint["protocol_step"] == "awaiting_build_review"
        assert checkpoint["required_tool"] == "review_loop"
        assert checkpoint["review_backend"] == "codex"
        assert checkpoint["challenge_backend"] == "claude"
        assert checkpoint["active_state_path"].endswith(f"docs/autopilot/runs/{prep['run_id']}/state.json")

        status = autopilot_status_tool(run_id=prep["run_id"])
        assert status["next_required_action"] == "Run the build review gate."
        assert status["artifact_refs"]["build"] == "docs/autopilot/runs/build-artifact.json"
        assert (tmp_path / "docs/autopilot/active-run.json").exists()

    def test_start_completes_run(self, tmp_path, monkeypatch):
        """autopilot_start runs pipeline to completion with real runners."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path)
        # Mock subprocess.run to prevent real command execution (verify/build
        # stages would otherwise run `python3 -m pytest` which re-enters the
        # test suite and causes infinite recursion).
        import subprocess
        _orig_run = subprocess.run

        def _mock_subprocess_run(cmd, **kwargs):
            # Allow git commands (used by build/ship), block test commands
            if isinstance(cmd, list) and cmd[0] == "git":
                return _orig_run(cmd, **kwargs)
            # Return success for all other commands (test runners)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="mock: passed", stderr=""
            )

        monkeypatch.setattr("subprocess.run", _mock_subprocess_run)
        from agentcouncil.server import autopilot_prepare_tool, autopilot_start_tool
        prep = autopilot_prepare_tool(
            intent="test", spec_id="s1", title="T", objective="O",
            requirements=["r1"], acceptance_criteria=["ac1"],
        )
        result = autopilot_start_tool(run_id=prep["run_id"])
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_resume_tool_returns_state(self, tmp_path, monkeypatch):
        """autopilot_resume continues a paused run."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path)
        # Mock subprocess.run to prevent real command execution (verify/build
        # stages would otherwise run `python3 -m pytest` which re-enters the
        # test suite and causes infinite recursion).
        import subprocess
        _orig_run = subprocess.run

        def _mock_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "git":
                return _orig_run(cmd, **kwargs)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="mock: passed", stderr=""
            )

        monkeypatch.setattr("subprocess.run", _mock_subprocess_run)
        # Create a run, manually set to paused_for_approval
        import time as _time
        run = AutopilotRun(
            run_id="resume-test", spec_id="s1", status="running",
            current_stage="plan", tier=2,
            stages=[
                StageCheckpoint(stage_name="spec_prep", status="advanced",
                    artifact_snapshot=_stub_spec_prep_artifact().model_dump()),
                StageCheckpoint(stage_name="plan", status="blocked"),
                StageCheckpoint(stage_name="build", status="pending"),
                StageCheckpoint(stage_name="verify", status="pending"),
                StageCheckpoint(stage_name="ship", status="pending"),
            ],
            started_at=_time.time(), updated_at=_time.time(),
        )
        validate_transition(run.status, "paused_for_approval")
        run.status = "paused_for_approval"
        persist(run)

        from agentcouncil.server import autopilot_resume_tool
        result = autopilot_resume_tool(run_id="resume-test")
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# TestVerifyRetryLoop — VER-04: verify->build retry loop
# ---------------------------------------------------------------------------


def _make_failed_verify_artifact(retry_recommendation: str = "retry_build") -> VerifyArtifact:
    """Return a VerifyArtifact with overall_status=failed and retry_recommendation set."""
    return VerifyArtifact(
        verify_id="verify-fail",
        build_id="build-1",
        plan_id="plan-1",
        spec_id="test-spec",
        test_environment=VerificationEnvironment(),
        criteria_verdicts=[
            CriterionVerification(
                criterion_id="ac-0",
                criterion_text="c",
                status="failed",
                verification_level="unit",
                mock_policy="not_applicable",
                evidence_summary="test failed",
                failure_diagnosis="Import error in module",
                revision_guidance="Fix the import",
            )
        ],
        overall_status="failed",
        retry_recommendation=retry_recommendation,
        revision_guidance="Fix the import error before retrying build",
    )


class TestVerifyRetryLoop:
    """VER-04: verify->build retry loop in LinearOrchestrator."""

    def test_retry_loop_reruns_build(self, run_dir):
        """When verify returns retry_recommendation=retry_build, build runner is called again."""
        registry = _make_test_registry()

        build_call_args = []

        def tracking_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            build_call_args.append(guidance)
            return _stub_build_artifact()

        # First verify call returns retry_build; second returns passed
        verify_call_count = [0]

        def verify_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            verify_call_count[0] += 1
            if verify_call_count[0] == 1:
                return _make_failed_verify_artifact("retry_build")
            return _stub_verify_artifact()

        runners = _make_stub_runners()
        runners["build"] = tracking_build_runner
        runners["verify"] = verify_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-reruns-build", tier=2)
        result = orchestrator.run_pipeline(run)

        # build should have been called twice: initial + after retry
        assert len(build_call_args) >= 2, (
            f"Expected build runner called at least twice, got {len(build_call_args)} calls"
        )
        assert result.status == "completed", (
            f"Expected completed after successful retry, got {result.status!r}"
        )

    def test_retry_loop_max_retries(self, run_dir):
        """After 2 retries, orchestrator sets status=paused_for_approval."""
        registry = _make_test_registry()

        # Verify always returns retry_build (exhausts retries)
        def always_fail_verify(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            return _make_failed_verify_artifact("retry_build")

        runners = _make_stub_runners()
        runners["verify"] = always_fail_verify

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-max-retries", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval after max retries, got {result.status!r}"
        )
        assert result.failure_reason is not None
        assert "retry loop exhausted" in result.failure_reason, (
            f"Expected failure_reason to mention retry loop exhausted, got {result.failure_reason!r}"
        )

    def test_no_retry_when_passed(self, run_dir):
        """When verify passes (retry_recommendation=none), build is called exactly once."""
        registry = _make_test_registry()

        build_call_count = [0]

        def tracking_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            build_call_count[0] += 1
            return _stub_build_artifact()

        runners = _make_stub_runners()
        runners["build"] = tracking_build_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="no-retry-when-passed", tier=2)
        result = orchestrator.run_pipeline(run)

        assert build_call_count[0] == 1, (
            f"Expected build runner called exactly once, got {build_call_count[0]}"
        )
        assert result.status == "completed"

    def test_revision_guidance_passed_to_build(self, run_dir):
        """revision_guidance from VerifyArtifact is passed to build runner on re-run."""
        registry = _make_test_registry()

        build_call_guidances = []

        def tracking_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            build_call_guidances.append(guidance)
            return _stub_build_artifact()

        # First verify fails with specific revision_guidance
        verify_call_count = [0]

        def verify_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            verify_call_count[0] += 1
            if verify_call_count[0] == 1:
                return _make_failed_verify_artifact("retry_build")
            return _stub_verify_artifact()

        runners = _make_stub_runners()
        runners["build"] = tracking_build_runner
        runners["verify"] = verify_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="revision-guidance-to-build", tier=2)
        orchestrator.run_pipeline(run)

        # First build call has no guidance, second has revision_guidance from verify artifact
        assert len(build_call_guidances) >= 2, (
            f"Expected at least 2 build calls, got {len(build_call_guidances)}"
        )
        assert build_call_guidances[0] is None, (
            f"First build call should have no guidance, got {build_call_guidances[0]!r}"
        )
        assert build_call_guidances[1] == "Fix the import error before retrying build", (
            f"Second build call should have revision_guidance, got {build_call_guidances[1]!r}"
        )


# ---------------------------------------------------------------------------
# Helpers for TestApprovalBoundary
# ---------------------------------------------------------------------------


def _make_external_stage_registry() -> dict[str, StageRegistryEntry]:
    """Return a modified registry where build has side_effect_level=external.

    This creates a registry where the approval guard should fire at build
    (build has review_loop gate by default, now with external side effects).
    """
    registry = load_default_registry()
    build_entry = registry["build"]
    raw = build_entry.manifest.model_dump()
    raw["side_effect_level"] = "external"
    new_manifest = StageManifest(**raw)
    registry["build"] = StageRegistryEntry(
        manifest=new_manifest,
        workflow_content=build_entry.workflow_content,
    )
    return registry


def _make_approval_required_registry() -> dict[str, StageRegistryEntry]:
    """Return a modified registry where plan has approval_required=True.

    plan has review_loop gate and side_effect_level=none, so this tests the
    unconditional approval_required flag.
    """
    registry = load_default_registry()
    plan_entry = registry["plan"]
    raw = plan_entry.manifest.model_dump()
    raw["approval_required"] = True
    new_manifest = StageManifest(**raw)
    registry["plan"] = StageRegistryEntry(
        manifest=new_manifest,
        workflow_content=plan_entry.workflow_content,
    )
    return registry


# ---------------------------------------------------------------------------
# TestApprovalBoundary — SAFE-01 and SAFE-02 behaviors
# ---------------------------------------------------------------------------


class TestApprovalBoundary:
    """Tests for SAFE-01 (three-tier classification) and SAFE-02 (pre-execution approval gate)."""

    # ------------------------------------------------------------------
    # _classify_stage unit tests (tests 1-5, SAFE-01)
    # ------------------------------------------------------------------

    def test_classify_executor_tier1_gate_none(self, run_dir):
        """_classify_stage returns 'executor' for tier=1 run with default_gate=none manifest."""
        registry = _make_test_registry()
        orchestrator = LinearOrchestrator(registry=registry, runners=_make_stub_runners())
        run = _make_run(run_id="classify-executor", tier=1)
        # spec_prep has default_gate=none and side_effect_level=none, approval_required=False
        entry = registry["spec_prep"]
        result = orchestrator._classify_stage(run, entry)
        assert result == "executor", f"Expected 'executor', got {result!r}"

    def test_classify_council_tier2_gate_review_loop_local(self, run_dir):
        """_classify_stage returns 'council' for tier=2 run with review_loop gate and local side effects."""
        registry = _make_test_registry()
        orchestrator = LinearOrchestrator(registry=registry, runners=_make_stub_runners())
        run = _make_run(run_id="classify-council", tier=2)
        # build has default_gate=review_loop and side_effect_level=local
        entry = registry["build"]
        assert entry.manifest.default_gate == "review_loop"
        assert entry.manifest.side_effect_level == "local"
        result = orchestrator._classify_stage(run, entry)
        assert result == "council", f"Expected 'council', got {result!r}"

    def test_classify_approval_gated_tier2_external(self, run_dir):
        """_classify_stage returns 'approval-gated' for tier=2 run with side_effect_level=external."""
        registry = _make_external_stage_registry()
        orchestrator = LinearOrchestrator(registry=registry, runners=_make_stub_runners())
        run = _make_run(run_id="classify-external", tier=2)
        # build has been modified to side_effect_level=external
        entry = registry["build"]
        assert entry.manifest.side_effect_level == "external"
        result = orchestrator._classify_stage(run, entry)
        assert result == "approval-gated", f"Expected 'approval-gated', got {result!r}"

    def test_classify_approval_gated_approval_required_true(self, run_dir):
        """_classify_stage returns 'approval-gated' when approval_required=True regardless of side_effect_level."""
        registry = _make_approval_required_registry()
        orchestrator = LinearOrchestrator(registry=registry, runners=_make_stub_runners())
        # Use tier=1 — even executor tier must be approval-gated if approval_required=True
        run = _make_run(run_id="classify-approval-required", tier=1)
        # plan has approval_required=True and side_effect_level=none
        entry = registry["plan"]
        assert entry.manifest.approval_required is True
        assert entry.manifest.side_effect_level == "none"
        result = orchestrator._classify_stage(run, entry)
        assert result == "approval-gated", (
            f"Expected 'approval-gated' for approval_required=True, got {result!r}"
        )

    def test_classify_approval_gated_tier3_external(self, run_dir):
        """_classify_stage returns 'approval-gated' for tier=3 run with side_effect_level=external."""
        registry = _make_external_stage_registry()
        orchestrator = LinearOrchestrator(registry=registry, runners=_make_stub_runners())
        run = _make_run(run_id="classify-tier3-external", tier=3)
        entry = registry["build"]
        assert entry.manifest.side_effect_level == "external"
        result = orchestrator._classify_stage(run, entry)
        assert result == "approval-gated", f"Expected 'approval-gated' for tier=3+external, got {result!r}"

    # ------------------------------------------------------------------
    # Approval guard integration tests (tests 6-9, SAFE-02)
    # ------------------------------------------------------------------

    def test_external_stage_pauses_before_execution(self, run_dir):
        """Pipeline with side_effect_level=external pauses at paused_for_approval BEFORE runner fires."""
        registry = _make_external_stage_registry()
        runners = _make_stub_runners()

        # Track calls on the build runner
        build_call_count = [0]

        def tracking_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            build_call_count[0] += 1
            return _stub_build_artifact()

        runners["build"] = tracking_build_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="external-pauses-before-exec", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval, got {result.status!r}"
        )
        assert build_call_count[0] == 0, (
            f"Runner must NOT fire before approval: call count={build_call_count[0]}"
        )
        assert result.current_stage == "build", (
            f"Expected current_stage=build, got {result.current_stage!r}"
        )
        build_checkpoint = next(
            (c for c in result.stages if c.stage_name == "build"), None
        )
        assert build_checkpoint is not None
        assert build_checkpoint.status == "blocked", (
            f"Expected build checkpoint status=blocked, got {build_checkpoint.status!r}"
        )

    def test_approval_required_true_pauses_regardless_of_tier(self, run_dir):
        """Pipeline with approval_required=True stage pauses regardless of tier (even tier=1)."""
        registry = _make_approval_required_registry()
        runners = _make_stub_runners()

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # tier=1 (executor) — should still pause because approval_required=True
        run = _make_run(run_id="approval-required-tier1", tier=1)
        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval for approval_required=True on tier=1, got {result.status!r}"
        )
        assert result.current_stage == "plan", (
            f"Expected current_stage=plan, got {result.current_stage!r}"
        )

    def test_local_stage_no_approval_pause(self, run_dir):
        """Pipeline with side_effect_level=local proceeds without approval pause."""
        # Default registry: all stages have side_effect_level=none or local, approval_required=False
        registry = _make_test_registry()
        runners = _make_stub_runners()

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="local-no-pause", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "completed", (
            f"Expected completed (no approval pause for local stages), got {result.status!r}"
        )

    def test_resume_from_approval_pause_completes(self, run_dir):
        """Block at external stage, resume by setting status=running; pipeline completes."""
        registry = _make_external_stage_registry()
        runners = _make_stub_runners()

        # Track build runner calls across both runs
        build_call_count = [0]

        def tracking_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ):
            build_call_count[0] += 1
            return _stub_build_artifact()

        runners["build"] = tracking_build_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }

        # First run: should pause at build (external)
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="resume-approval-pause", tier=2)
        blocked_run = orchestrator.run_pipeline(run)
        assert blocked_run.status == "paused_for_approval", (
            f"Expected paused_for_approval after first run, got {blocked_run.status!r}"
        )
        assert build_call_count[0] == 0, (
            "Build runner must not fire during first (approval-paused) run"
        )

        # Second run: load run, set status=running, run again (this is the resume/approval flow)
        from agentcouncil.autopilot.run import load_run
        resumed_run = load_run("resume-approval-pause")
        resumed_run.status = "running"  # type: ignore[assignment]

        orchestrator2 = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator2.run_pipeline(resumed_run)

        assert result.status == "completed", (
            f"Expected completed after resume+approval, got {result.status!r}"
        )
        assert build_call_count[0] >= 1, (
            f"Build runner must fire during second (resumed) run, got call_count={build_call_count[0]}"
        )


# ---------------------------------------------------------------------------
# TestRuleBasedRouter — SAFE-03 and SAFE-04 integration
# ---------------------------------------------------------------------------


class TestRuleBasedRouter:
    """Integration tests for rule-based tier router and dynamic tier promotion.

    SAFE-03: classify_run assigns tier=3 for sensitive target_files before execution.
    SAFE-04: _maybe_promote_tier promotes tier when BuildArtifact.files_changed contains
             undeclared sensitive paths.
    """

    def test_tier3_assigned_for_sensitive_target_files(self, run_dir):
        """Run with spec_target_files=["src/auth/x.py"] should trigger challenge gate (tier=3)."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        challenge_called = [False]

        def tracking_challenge_gate() -> GateDecision:
            challenge_called[0] = True
            return GateDecision(
                decision="advance",
                protocol_type="challenge",
                protocol_session_id="stub",
                rationale="ok",
            )

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": tracking_challenge_gate,
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # Set tier=3 (already classified via classify_run) with auth target_files
        run = _make_run(run_id="router-tier3-run", tier=3)
        run.spec_target_files = ["src/auth/x.py"]

        result = orchestrator.run_pipeline(run)

        # tier=3 triggers challenge gate (ORCH-05)
        assert result.tier == 3
        assert orchestrator._should_run_challenge(result) is True

    def test_tier_promotion_on_undeclared_sensitive_build(self, run_dir):
        """Build returning files_changed with undeclared permissions/ path should promote tier."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        # Build runner that returns a BuildArtifact with an undeclared sensitive file
        def sensitive_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ) -> BuildArtifact:
            return BuildArtifact(
                build_id="build-promo",
                plan_id="plan-1",
                spec_id="test-spec",
                evidence=[
                    BuildEvidence(
                        task_id="t1",
                        files_changed=["src/permissions/roles.py"],
                        verification_notes="built",
                    )
                ],
                all_tests_passing=True,
                files_changed=["src/permissions/roles.py"],
            )

        runners["build"] = sensitive_build_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # Start at tier=2 with no sensitive target_files declared
        run = _make_run(run_id="router-promo-run", tier=2)
        run.spec_target_files = ["src/main.py"]  # no sensitive paths declared

        result = orchestrator.run_pipeline(run)

        assert result.tier == 3, (
            f"Expected tier promoted to 3 after undeclared permissions/ file, got {result.tier}"
        )
        assert result.tier_promoted_at is not None, (
            "tier_promoted_at must be set after promotion"
        )

    def test_no_promotion_when_files_declared(self, run_dir):
        """Build touching auth/ paths that were declared in spec should NOT promote tier."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        def auth_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ) -> BuildArtifact:
            return BuildArtifact(
                build_id="build-declared",
                plan_id="plan-1",
                spec_id="test-spec",
                evidence=[
                    BuildEvidence(
                        task_id="t1",
                        files_changed=["src/auth/x.py"],
                        verification_notes="built",
                    )
                ],
                all_tests_passing=True,
                files_changed=["src/auth/x.py"],
            )

        runners["build"] = auth_build_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        # Declare auth in spec_target_files — auth/ path is covered
        run = _make_run(run_id="router-no-promo-run", tier=2)
        run.spec_target_files = ["src/auth/x.py"]

        result = orchestrator.run_pipeline(run)

        # tier should remain at 2 because auth/ was declared
        assert result.tier == 2, (
            f"Expected tier unchanged at 2 (auth declared), got {result.tier}"
        )
        assert result.tier_promoted_at is None, (
            "tier_promoted_at should remain None when no undeclared sensitive files"
        )

    def test_promotion_sticky_across_stages(self, run_dir):
        """After tier promotion in build stage, _should_run_challenge should return True."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        def sensitive_build_runner(
            run: AutopilotRun, reg: dict, guidance: Optional[str] = None
        ) -> BuildArtifact:
            return BuildArtifact(
                build_id="build-sticky",
                plan_id="plan-1",
                spec_id="test-spec",
                evidence=[
                    BuildEvidence(
                        task_id="t1",
                        files_changed=["db/migrations/001.sql"],
                        verification_notes="built",
                    )
                ],
                all_tests_passing=True,
                files_changed=["db/migrations/001.sql"],
            )

        runners["build"] = sensitive_build_runner

        challenge_called = [False]

        def tracking_challenge_gate() -> GateDecision:
            challenge_called[0] = True
            return GateDecision(
                decision="advance",
                protocol_type="challenge",
                protocol_session_id="stub",
                rationale="ok",
            )

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": tracking_challenge_gate,
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="router-sticky-run", tier=2)
        run.spec_target_files = ["src/utils.py"]  # no sensitive paths declared

        result = orchestrator.run_pipeline(run)

        # Tier should be promoted to 3
        assert result.tier == 3, f"Expected tier=3 after promotion, got {result.tier}"
        # Challenge gate should have fired (tier=3 triggers it)
        assert challenge_called[0] is True, "Challenge gate must fire after tier promotion to 3"

    def test_no_demotion_on_resume(self, run_dir):
        """Persisted run with promoted tier=3 should retain tier=3 after load."""
        from agentcouncil.autopilot.run import load_run as _load_run, persist as _persist

        run = _make_run(run_id="router-no-demotion", tier=3)
        run.tier_promoted_at = datetime.now(timezone.utc).isoformat()
        _persist(run)

        loaded = _load_run("router-no-demotion")
        assert loaded.tier == 3, (
            f"Tier must be 3 after persisting promoted run, got {loaded.tier}"
        )
        assert loaded.tier_promoted_at is not None, "tier_promoted_at must be preserved"


# ---------------------------------------------------------------------------
# Helpers for TestFailureHandling and TestDynamicGatePromotion
# ---------------------------------------------------------------------------


class _ExceptionThenAdvanceGate:
    """Gate stub that raises Exception on first call, returns advance on second."""

    def __init__(self):
        self.call_count = 0

    def __call__(self) -> GateDecision:
        self.call_count += 1
        if self.call_count == 1:
            raise Exception("gate timeout")
        return GateDecision(
            decision="advance",
            protocol_type="review_loop",
            protocol_session_id="stub",
            rationale="ok after retry",
        )


class _AlwaysExceptionGate:
    """Gate stub that always raises Exception."""

    def __init__(self):
        self.call_count = 0

    def __call__(self) -> GateDecision:
        self.call_count += 1
        raise Exception("gate timeout")


def _make_registry_with_retry_policy(stage_name: str, retry_policy: str) -> dict:
    """Return a registry copy where the given stage has a custom retry_policy."""
    registry = load_default_registry()
    entry = registry[stage_name]
    raw = entry.manifest.model_dump()
    raw["retry_policy"] = retry_policy
    new_manifest = StageManifest(**raw)
    registry[stage_name] = StageRegistryEntry(
        manifest=new_manifest,
        workflow_content=entry.workflow_content,
    )
    return registry


# ---------------------------------------------------------------------------
# TestFailureHandling — SAFE-05 retry policy and exhaustion behaviors
# ---------------------------------------------------------------------------


class TestFailureHandling:
    """SAFE-05: Gate retry policy enforcement, exhaustion escalation, checkpoint resume."""

    def test_gate_retry_once_on_exception(self, run_dir):
        """Gate raises on first call, returns advance on second. With retry_policy='once', stage advances."""
        # plan has review_loop gate — modify its retry_policy to "once"
        registry = _make_registry_with_retry_policy("plan", "once")
        runners = _make_stub_runners()

        exception_then_advance = _ExceptionThenAdvanceGate()
        gate_runners = {
            "review_loop": exception_then_advance,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-once-advance", tier=2)
        result = orchestrator.run_pipeline(run)

        # Retry succeeded — run should complete
        assert result.status == "completed", (
            f"Expected completed after successful retry, got {result.status!r}"
        )
        # Gate was called at least twice (initial fail + retry)
        assert exception_then_advance.call_count >= 2, (
            f"Expected gate called at least twice, got {exception_then_advance.call_count}"
        )

    def test_gate_retry_none_no_retry(self, run_dir):
        """Gate raises with retry_policy='none' — no retry, run transitions to paused_for_approval."""
        # plan has review_loop gate — set retry_policy to "none"
        registry = _make_registry_with_retry_policy("plan", "none")
        runners = _make_stub_runners()

        always_exception = _AlwaysExceptionGate()
        gate_runners = {
            "review_loop": always_exception,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-none-pauses", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval with retry_policy=none, got {result.status!r}"
        )
        # With retry_policy=none, gate should have been called exactly once
        assert always_exception.call_count == 1, (
            f"Expected gate called exactly once with retry_policy=none, got {always_exception.call_count}"
        )
        assert result.failure_reason is not None, "failure_reason must be set on gate failure"

    def test_gate_retry_backend_fallback_uses_fallback_runner(self, run_dir):
        """With retry_policy='backend_fallback', orchestrator calls fallback gate runner on exception."""
        # Modify plan's retry_policy to backend_fallback
        registry = _make_registry_with_retry_policy("plan", "backend_fallback")
        runners = _make_stub_runners()

        fallback_called = [False]

        def fallback_gate() -> GateDecision:
            fallback_called[0] = True
            return GateDecision(
                decision="advance",
                protocol_type="review_loop",
                protocol_session_id="fallback-stub",
                rationale="fallback gate passed",
            )

        # Only plan should fail — use a gate that fails on first call for plan
        # then succeeds on subsequent calls for build
        exception_then_advance = _ExceptionThenAdvanceGate()
        gate_runners = {
            "review_loop": exception_then_advance,
            "review_loop_fallback": fallback_gate,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-backend-fallback", tier=2)
        result = orchestrator.run_pipeline(run)

        assert fallback_called[0] is True, (
            "Fallback gate runner must be called with retry_policy=backend_fallback"
        )
        assert result.status == "completed", (
            f"Expected completed after fallback gate advance, got {result.status!r}"
        )

    def test_gate_retry_backend_fallback_no_fallback_registered(self, run_dir):
        """retry_policy='backend_fallback' with no fallback runner — retries primary gate once."""
        registry = _make_registry_with_retry_policy("plan", "backend_fallback")
        runners = _make_stub_runners()

        exception_then_advance = _ExceptionThenAdvanceGate()
        gate_runners = {
            "review_loop": exception_then_advance,
            # No review_loop_fallback registered
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-backend-no-fallback", tier=2)
        result = orchestrator.run_pipeline(run)

        # No fallback: retries primary once — second call returns advance
        assert result.status == "completed", (
            f"Expected completed (primary retry succeeds), got {result.status!r}"
        )
        assert exception_then_advance.call_count >= 2, (
            f"Expected primary gate called at least twice (retry), got {exception_then_advance.call_count}"
        )

    def test_exhausted_retries_pause_with_failure_reason(self, run_dir):
        """Gate always raises, retry_policy='once'. After exhaustion, status=paused_for_approval and failure_reason set."""
        registry = _make_registry_with_retry_policy("plan", "once")
        runners = _make_stub_runners()

        always_exception = _AlwaysExceptionGate()
        gate_runners = {
            "review_loop": always_exception,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="retry-exhausted-pauses", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval after retry exhaustion, got {result.status!r}"
        )
        assert result.failure_reason is not None, "failure_reason must be set on exhaustion"
        assert "plan" in result.failure_reason, (
            f"failure_reason should mention stage name 'plan', got {result.failure_reason!r}"
        )
        assert "gate" in result.failure_reason.lower() or "review_loop" in result.failure_reason, (
            f"failure_reason should mention gate info, got {result.failure_reason!r}"
        )

    def test_mid_pipeline_failure_has_checkpoints(self, run_dir):
        """spec_prep and plan complete; build gate raises. Completed stages have artifact_snapshot."""
        # Modify build's retry_policy to "none" so first exception causes immediate failure
        registry = _make_registry_with_retry_policy("build", "none")
        runners = _make_stub_runners()

        always_exception = _AlwaysExceptionGate()
        gate_runners = {
            "review_loop": _AdvanceGate(),  # plan gate passes
            "challenge": _AdvanceGate(),
        }

        # Override build gate to fail
        class BuildFailGateRunners:
            def __init__(self):
                self.call_count = 0

            def get_gate(self, gate_type):
                if gate_type == "review_loop" and self.call_count == 0:
                    # First review_loop call is for plan (advance)
                    # But wait — we need to differentiate plan vs build gate calls
                    pass

        # Use a counter to fail only on build's gate call
        # plan uses review_loop (call 1) → advance
        # build uses review_loop (call 2) → exception
        call_count = [0]

        def selective_fail_gate() -> GateDecision:
            call_count[0] += 1
            if call_count[0] == 1:
                # First call is plan gate — advance
                return GateDecision(
                    decision="advance",
                    protocol_type="review_loop",
                    protocol_session_id="stub",
                    rationale="plan ok",
                )
            # Second call is build gate — raise
            raise Exception("build gate timeout")

        gate_runners_selective = {
            "review_loop": selective_fail_gate,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners_selective,
        )
        run = _make_run(run_id="mid-pipeline-checkpoints", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "paused_for_approval", (
            f"Expected paused_for_approval after build gate failure, got {result.status!r}"
        )
        # spec_prep and plan should be advanced with artifact_snapshot
        for stage_name in ("spec_prep", "plan"):
            cp = next((c for c in result.stages if c.stage_name == stage_name), None)
            assert cp is not None, f"Missing checkpoint for {stage_name}"
            assert cp.status == "advanced", (
                f"Stage {stage_name!r} should be advanced, got {cp.status!r}"
            )
            assert cp.artifact_snapshot is not None, (
                f"Stage {stage_name!r} should have artifact_snapshot populated"
            )

    def test_resume_after_gate_failure_continues_from_checkpoint(self, run_dir):
        """After mid-pipeline gate failure, resume() reconstructs artifact_registry from checkpoints."""
        # Block at build gate with retry_policy=none
        registry = _make_registry_with_retry_policy("build", "none")
        runners = _make_stub_runners()

        call_count = [0]

        def selective_fail_gate() -> GateDecision:
            call_count[0] += 1
            if call_count[0] == 1:
                return GateDecision(
                    decision="advance",
                    protocol_type="review_loop",
                    protocol_session_id="stub",
                    rationale="plan ok",
                )
            raise Exception("build gate timeout")

        gate_runners_fail = {
            "review_loop": selective_fail_gate,
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners_fail,
        )
        run = _make_run(run_id="resume-after-failure", tier=2)
        failed_run = orchestrator.run_pipeline(run)
        assert failed_run.status == "paused_for_approval"

        # Resume: reconstruct artifact registry from checkpoints
        resumed_run, artifact_registry = resume("resume-after-failure")

        # artifact_registry should have spec_prep and plan artifacts reconstructed
        assert "spec_prep" in artifact_registry, (
            "resume() must reconstruct spec_prep artifact from checkpoint"
        )
        assert "plan" in artifact_registry, (
            "resume() must reconstruct plan artifact from checkpoint"
        )

        # Now complete the run with a passing build gate
        registry2 = load_default_registry()
        gate_runners_pass = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator2 = LinearOrchestrator(
            registry=registry2,
            runners=runners,
            gate_runners=gate_runners_pass,
        )
        resumed_run.status = "running"  # type: ignore[assignment]
        result = orchestrator2.run_pipeline(resumed_run, artifact_registry)
        assert result.status == "completed", (
            f"Expected completed after resume from gate failure, got {result.status!r}"
        )


# ---------------------------------------------------------------------------
# TestDynamicGatePromotion — SAFE-05 SC4: gate-outcome-driven tier promotion
# ---------------------------------------------------------------------------


def _make_challenge_not_ready_artifact():
    """Create a valid ChallengeArtifact with readiness='not_ready'."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode
    return ChallengeArtifact(
        readiness="not_ready",
        summary="Challenge identified critical risks",
        failure_modes=[
            FailureMode(
                id="fm-1",
                assumption_ref="a-1",
                description="Critical failure mode",
                severity="critical",
                impact="System unavailable",
                confidence="high",
                disposition="must_harden",
            )
        ],
        next_action="Harden the system before proceeding",
    )


def _make_convergence_result_with_finding(severity: str):
    """Create a ConvergenceResult with a Finding of the given severity."""
    from agentcouncil.schemas import ConvergenceResult, Finding
    return ConvergenceResult(
        total_iterations=1,
        exit_reason="all_verified",
        final_verdict="pass",
        final_findings=[
            Finding(
                id="f-1",
                title="Security issue",
                severity=severity,
                impact="High impact",
                description="Description of issue",
                evidence="Code evidence",
                confidence="high",
                agreement="confirmed",
                origin="outside",
            )
        ],
    )


def _make_review_artifact_with_finding(severity: str):
    """Create a ReviewArtifact with a Finding of the given severity."""
    from agentcouncil.schemas import ReviewArtifact, Finding
    return ReviewArtifact(
        verdict="pass",
        summary="Review with finding",
        findings=[
            Finding(
                id="f-1",
                title="Security issue",
                severity=severity,
                impact="High impact",
                description="Description of issue",
                evidence="Code evidence",
                confidence="high",
                agreement="confirmed",
                origin="outside",
            )
        ],
        next_action="Address finding",
    )


class TestDynamicGatePromotion:
    """SAFE-05 SC4: Tier promotion triggered by gate-outcome inspection."""

    def test_challenge_not_ready_promotes_to_tier3(self, run_dir):
        """Challenge gate returning not_ready promotes run.tier to 3."""
        from agentcouncil.schemas import ChallengeArtifact, FailureMode

        # Use external verify registry so challenge gate fires for tier=2 run (ORCH-05)
        registry = _make_external_verify_registry()
        runners = _make_stub_runners()

        challenge_artifact = _make_challenge_not_ready_artifact()

        # Use a subclass that overrides _run_gate to inject the not_ready artifact
        class _InjectNotReadyChallengeOrchestrator(LinearOrchestrator):
            def _run_gate(self, gate_type: str, prior_review_context: str | None = None) -> GateDecision:
                if gate_type == "challenge":
                    self._last_raw_artifact = challenge_artifact
                    return GateDecision(
                        decision="block",
                        protocol_type="challenge",
                        protocol_session_id="stub-not-ready",
                        rationale="not_ready -> block",
                    )
                return super()._run_gate(gate_type)

        # Start pipeline at verify with tier=2; external verify triggers challenge gate.
        # Pre-set verify checkpoint to "blocked" (approval already granted) to bypass
        # the pre-execution approval guard for this external-side-effect stage.
        run = _make_run(run_id="challenge-not-ready-promo", tier=2, current_stage="verify")
        artifact_registry = {
            "spec_prep": _stub_spec_prep_artifact(),
            "plan": _stub_plan_artifact(),
            "build": _stub_build_artifact(),
        }
        for checkpoint in run.stages:
            if checkpoint.stage_name in ("spec_prep", "plan", "build"):
                checkpoint.status = "advanced"
        verify_cp = next(c for c in run.stages if c.stage_name == "verify")
        verify_cp.status = "blocked"  # simulates approval already granted

        gate_runners = {
            "review_loop": _AdvanceGate(),
        }
        orchestrator = _InjectNotReadyChallengeOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator.run_pipeline(run, artifact_registry=artifact_registry)

        # After challenge gate with not_ready raw artifact, tier should be promoted to 3
        assert result.tier == 3, (
            f"Expected tier=3 after challenge not_ready, got {result.tier}"
        )
        assert result.tier_promoted_at is not None, (
            "tier_promoted_at must be set after gate-triggered promotion"
        )

    def test_review_critical_finding_promotes_to_tier3(self, run_dir):
        """Review gate with a critical finding promotes run.tier to 3."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        convergence_result = _make_convergence_result_with_finding("critical")

        class _InjectCriticalFindingOrchestrator(LinearOrchestrator):
            def _run_gate(self, gate_type: str, prior_review_context: str | None = None) -> GateDecision:
                if gate_type == "review_loop":
                    self._last_raw_artifact = convergence_result
                    return GateDecision(
                        decision="advance",
                        protocol_type="review_loop",
                        protocol_session_id="stub-critical",
                        rationale="pass but has critical finding",
                    )
                return super()._run_gate(gate_type)

        run = _make_run(run_id="review-critical-promo", tier=2)
        gate_runners = {
            "challenge": _AdvanceGate(),
        }
        orchestrator = _InjectCriticalFindingOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator.run_pipeline(run)

        assert result.tier == 3, (
            f"Expected tier=3 after critical finding in review gate, got {result.tier}"
        )
        assert result.tier_promoted_at is not None

    def test_review_high_finding_promotes_to_tier3(self, run_dir):
        """Review gate with a high-severity finding promotes run.tier to 3."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        convergence_result = _make_convergence_result_with_finding("high")

        class _InjectHighFindingOrchestrator(LinearOrchestrator):
            def _run_gate(self, gate_type: str, prior_review_context: str | None = None) -> GateDecision:
                if gate_type == "review_loop":
                    self._last_raw_artifact = convergence_result
                    return GateDecision(
                        decision="advance",
                        protocol_type="review_loop",
                        protocol_session_id="stub-high",
                        rationale="pass but has high finding",
                    )
                return super()._run_gate(gate_type)

        run = _make_run(run_id="review-high-promo", tier=2)
        gate_runners = {
            "challenge": _AdvanceGate(),
        }
        orchestrator = _InjectHighFindingOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator.run_pipeline(run)

        assert result.tier == 3, (
            f"Expected tier=3 after high finding in review gate, got {result.tier}"
        )
        assert result.tier_promoted_at is not None

    def test_review_low_finding_no_promotion(self, run_dir):
        """Review gate with only low/medium findings does NOT promote tier."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        convergence_result = _make_convergence_result_with_finding("low")

        class _InjectLowFindingOrchestrator(LinearOrchestrator):
            def _run_gate(self, gate_type: str, prior_review_context: str | None = None) -> GateDecision:
                if gate_type == "review_loop":
                    self._last_raw_artifact = convergence_result
                    return GateDecision(
                        decision="advance",
                        protocol_type="review_loop",
                        protocol_session_id="stub-low",
                        rationale="pass, low finding only",
                    )
                return super()._run_gate(gate_type)

        run = _make_run(run_id="review-low-no-promo", tier=2)
        gate_runners = {
            "challenge": _AdvanceGate(),
        }
        orchestrator = _InjectLowFindingOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator.run_pipeline(run)

        assert result.tier == 2, (
            f"Expected tier=2 (no promotion for low finding), got {result.tier}"
        )
        assert result.tier_promoted_at is None, (
            "tier_promoted_at must remain None for low/medium findings"
        )

    def test_promotion_persisted_before_next_stage(self, run_dir):
        """After gate-triggered promotion, persist(run) is called with tier=3 BEFORE next stage runner fires."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        convergence_result = _make_convergence_result_with_finding("critical")

        # Track the tier value seen by the build runner
        tier_at_build_call = [None]

        def tracking_build_runner(
            run: AutopilotRun, reg: dict, guidance=None
        ):
            tier_at_build_call[0] = run.tier
            return _stub_build_artifact()

        runners["build"] = tracking_build_runner

        class _InjectCriticalFindingPlanOrchestrator(LinearOrchestrator):
            def _run_gate(self, gate_type: str, prior_review_context: str | None = None) -> GateDecision:
                if gate_type == "review_loop":
                    self._last_raw_artifact = convergence_result
                    return GateDecision(
                        decision="advance",
                        protocol_type="review_loop",
                        protocol_session_id="stub-plan-critical",
                        rationale="plan pass but has critical finding",
                    )
                return super()._run_gate(gate_type)

        run = _make_run(run_id="promo-before-next-stage", tier=2)
        gate_runners = {
            "challenge": _AdvanceGate(),
        }
        orchestrator = _InjectCriticalFindingPlanOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator.run_pipeline(run)

        # Build runner should see tier=3 (promoted by plan gate before build runs)
        assert tier_at_build_call[0] == 3, (
            f"Expected build runner to see tier=3 after plan gate promotion, got {tier_at_build_call[0]}"
        )

    def test_already_tier3_no_double_promotion(self, run_dir):
        """If run.tier is already 3, gate-triggered promotion is a no-op (tier_promoted_at not overwritten)."""
        registry = _make_test_registry()
        runners = _make_stub_runners()

        convergence_result = _make_convergence_result_with_finding("critical")

        original_promoted_at = "2026-01-01T00:00:00+00:00"

        class _InjectCriticalFindingOrchestrator(LinearOrchestrator):
            def _run_gate(self, gate_type: str, prior_review_context: str | None = None) -> GateDecision:
                if gate_type == "review_loop":
                    self._last_raw_artifact = convergence_result
                    return GateDecision(
                        decision="advance",
                        protocol_type="review_loop",
                        protocol_session_id="stub-already-tier3",
                        rationale="pass but critical finding",
                    )
                return super()._run_gate(gate_type)

        # Run already at tier=3 with a pre-existing promotion timestamp
        run = _make_run(run_id="already-tier3-no-double-promo", tier=3)
        run.tier_promoted_at = original_promoted_at

        gate_runners = {
            "challenge": _AdvanceGate(),
        }
        orchestrator = _InjectCriticalFindingOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        result = orchestrator.run_pipeline(run)

        # Tier should remain 3, and tier_promoted_at should NOT be overwritten
        assert result.tier == 3, f"Expected tier=3, got {result.tier}"
        assert result.tier_promoted_at == original_promoted_at, (
            f"tier_promoted_at must not be overwritten for already-tier3 run, "
            f"got {result.tier_promoted_at!r}"
        )


# ---------------------------------------------------------------------------
# Review fix tests — F2, F3, F6
# ---------------------------------------------------------------------------


class TestReviewFixes:
    """Tests added from code review findings F2, F3, F6."""

    @pytest.fixture(autouse=True)
    def run_dir(self, tmp_path, monkeypatch):
        import agentcouncil.autopilot.run as run_mod
        monkeypatch.setattr(run_mod, "RUN_DIR", tmp_path)
        return tmp_path

    def test_max_revise_exhaustion_reaches_failed(self):
        """F2: Exhausting max_revise_iterations transitions to status=failed."""
        registry = _make_test_registry()

        class _AlwaysReviseGate:
            def __call__(self, *args, **kwargs):
                return GateDecision(
                    decision="revise",
                    protocol_type="review_loop",
                    protocol_session_id="stub",
                    rationale="always revise",
                    revision_guidance="fix it",
                )

        gate_runners = {
            "review_loop": _AlwaysReviseGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=_make_stub_runners(),
            gate_runners=gate_runners,
            max_revise_iterations=2,
        )
        run = _make_run(run_id="max-revise-exhaust", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "failed", (
            f"Expected failed after max revise, got {result.status!r}"
        )
        assert result.failure_reason is not None
        assert "max revise" in result.failure_reason.lower(), (
            f"Expected 'max revise' in failure_reason, got {result.failure_reason!r}"
        )

    def test_runner_exception_transitions_to_failed(self):
        """F3: A runner that raises transitions run to status=failed with diagnostic."""
        registry = _make_test_registry()

        def _crashing_runner(run, reg, guidance=None):
            raise RuntimeError("network timeout")

        runners = _make_stub_runners()
        runners["build"] = _crashing_runner

        gate_runners = {
            "review_loop": _AdvanceGate(),
            "challenge": _AdvanceGate(),
        }
        orchestrator = LinearOrchestrator(
            registry=registry,
            runners=runners,
            gate_runners=gate_runners,
        )
        run = _make_run(run_id="runner-crash", tier=2)
        result = orchestrator.run_pipeline(run)

        assert result.status == "failed", (
            f"Expected failed after runner crash, got {result.status!r}"
        )
        assert "build" in result.failure_reason
        assert "RuntimeError" in result.failure_reason
        assert "network timeout" in result.failure_reason

    def test_gate_promotion_challenge_not_ready(self):
        """F6: _maybe_promote_from_gate promotes tier on ChallengeArtifact(readiness=not_ready)."""
        from agentcouncil.schemas import ChallengeArtifact

        orch = LinearOrchestrator(
            registry=_make_test_registry(),
            runners=_make_stub_runners(),
        )
        run = _make_run(run_id="promo-challenge", tier=2)
        from agentcouncil.schemas import FailureMode
        challenge_art = ChallengeArtifact(
            readiness="not_ready",
            summary="not ready",
            failure_modes=[FailureMode(
                id="fm1", assumption_ref="a1", description="critical failure",
                severity="critical", impact="high", confidence="high",
                disposition="must_harden",
            )],
            next_action="address issues",
        )
        orch._maybe_promote_from_gate(run, "challenge", challenge_art)
        assert run.tier == 3, f"Expected tier=3 after not_ready challenge, got {run.tier}"
        assert run.tier_promoted_at is not None

    def test_gate_promotion_review_critical_finding(self):
        """F6: _maybe_promote_from_gate promotes tier on review with critical finding."""
        from agentcouncil.schemas import ConvergenceResult, Finding

        orch = LinearOrchestrator(
            registry=_make_test_registry(),
            runners=_make_stub_runners(),
        )
        run = _make_run(run_id="promo-review-crit", tier=1)
        convergence = ConvergenceResult(
            final_verdict="pass",
            exit_reason="all_verified",
            final_findings=[
                Finding(
                    id="f1", title="Critical issue", severity="critical",
                    impact="high", description="Something critical",
                    evidence="line 42", locations=["file.py"],
                    confidence="high", agreement="confirmed", origin="outside",
                ),
            ],
            total_iterations=1,
        )
        orch._maybe_promote_from_gate(run, "review_loop", convergence)
        assert run.tier == 3, f"Expected tier=3 after critical finding, got {run.tier}"

    def test_gate_promotion_no_op_for_clean_gate(self):
        """F6: _maybe_promote_from_gate does NOT promote on clean gate outcomes."""
        from agentcouncil.schemas import ChallengeArtifact

        orch = LinearOrchestrator(
            registry=_make_test_registry(),
            runners=_make_stub_runners(),
        )
        run = _make_run(run_id="promo-clean", tier=2)
        clean_challenge = ChallengeArtifact(
            readiness="ready",
            summary="all good",
            failure_modes=[],
            next_action="ship it",
        )
        orch._maybe_promote_from_gate(run, "challenge", clean_challenge)
        assert run.tier == 2, f"Expected tier=2 (no promotion), got {run.tier}"


class _RaisingGateExecutor:
    """Fake gate executor that always raises RuntimeError."""
    def run_gate(self, gate_type, **kwargs):
        raise RuntimeError("backend unavailable")


class TestGateExecutorExceptionPropagates:
    def test_gate_executor_exception_propagates_not_swallowed(self):
        """Gate executor failure must raise, not silently fall through to stub."""
        orchestrator = LinearOrchestrator(
            registry=_make_test_registry(),
            runners=_make_stub_runners(),
            gate_executor=_RaisingGateExecutor(),
        )
        # _run_gate should raise when executor raises
        with pytest.raises(RuntimeError, match="backend unavailable"):
            orchestrator._run_gate("review_loop")
