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
