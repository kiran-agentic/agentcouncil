"""Tests for agentcouncil/autopilot/orchestrator.py — ORCH-03 and ORCH-05 behaviors.

Covers:
- ORCH-03: LinearOrchestrator sequences work stages through the full pipeline
  with gate loop (advance / revise / block) and persist at every checkpoint.
- ORCH-05: Challenge gate fires conditionally after verify (side_effect_level=external
  or tier=3); skipped for tier=2 with non-external side effects.
"""
from __future__ import annotations

import time
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
        """Challenge gate is invoked after verify when side_effect_level=external."""
        registry = _make_external_verify_registry()
        runners = _make_stub_runners()

        challenge_gate = _AdvanceGate()
        challenge_called = []

        def tracking_challenge(run=None, reg=None, guidance=None):
            challenge_called.append(True)
            return _stub_ship_artifact()  # not used directly

        # Wrap challenge gate to track calls
        original_challenge = challenge_gate

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
        run = _make_run(run_id="challenge-external-run", tier=2)
        result = orchestrator.run_pipeline(run)

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
        assert len(status["stages"]) == 5

    def test_start_completes_run(self, tmp_path, monkeypatch):
        """autopilot_start runs pipeline to completion with stubs."""
        monkeypatch.setattr("agentcouncil.autopilot.run.RUN_DIR", tmp_path)
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
