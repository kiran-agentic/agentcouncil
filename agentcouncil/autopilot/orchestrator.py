"""agentcouncil.autopilot.orchestrator — LinearOrchestrator for autopilot pipeline.

Implements the central state machine that sequences stub work stages through the
full autopilot pipeline (spec_prep -> plan -> build -> verify -> ship), persisting
state at every checkpoint, enforcing gate transitions (advance/revise/block), and
conditionally running the challenge gate after verify.

Requirements addressed:
- ORCH-03: Linear stage sequencing with gate loop (advance/revise/block)
- ORCH-05: Conditional challenge gate after verify (side_effect_level=external or tier=3)
- SAFE-01: Three-tier autonomy model with per-stage classification (executor/council/approval-gated)
- SAFE-02: Approval boundary blocks external side effects pending human approval
- SAFE-05: Failure handling with retry policy, exhaustion escalation, and gate-outcome promotion
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from agentcouncil.autopilot.artifacts import (
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
)
from agentcouncil.autopilot.loader import StageRegistryEntry, load_default_registry
from agentcouncil.autopilot.normalizer import GateNormalizer
from agentcouncil.autopilot.router import detect_undeclared_sensitive_files
from agentcouncil.autopilot.run import (
    AutopilotRun,
    StageCheckpoint,
    persist,
    validate_transition,
)

try:
    from agentcouncil.schemas import ChallengeArtifact, ConvergenceResult, ReviewArtifact
except ImportError:
    ChallengeArtifact = None  # type: ignore[assignment,misc]
    ConvergenceResult = None  # type: ignore[assignment,misc]
    ReviewArtifact = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

#: Callable signature for a stage runner.
#: Args: (run, artifact_registry, revision_guidance) -> artifact
#: revision_guidance is None on first call; str on revise re-run.
StageRunner = Callable[[AutopilotRun, dict[str, Any], Optional[str]], Any]


# ---------------------------------------------------------------------------
# Stub artifact factories (used as default runners)
# ---------------------------------------------------------------------------


def _stub_spec_prep_artifact() -> SpecPrepArtifact:
    return SpecPrepArtifact(
        prep_id="prep-stub",
        finalized_spec=SpecArtifact(
            spec_id="stub-spec",
            title="Stub",
            objective="Stub objective",
            requirements=["r1"],
            acceptance_criteria=["ac-1"],
        ),
        research=CodebaseResearchBrief(summary="stub research"),
        clarification=ClarificationPlan(),
    )


def _stub_plan_artifact() -> PlanArtifact:
    return PlanArtifact(
        plan_id="plan-stub",
        spec_id="stub-spec",
        tasks=[
            PlanTask(
                task_id="t1",
                title="Stub Task",
                description="stub",
                acceptance_criteria=["ac-1"],
            )
        ],
        execution_order=["t1"],
        verification_strategy="run pytest",
    )


def _stub_build_artifact() -> BuildArtifact:
    return BuildArtifact(
        build_id="build-stub",
        plan_id="plan-stub",
        spec_id="stub-spec",
        evidence=[
            BuildEvidence(
                task_id="t1",
                files_changed=["stub.py"],
                verification_notes="stub build",
            )
        ],
        all_tests_passing=True,
        files_changed=["stub.py"],
    )


def _stub_verify_artifact() -> VerifyArtifact:
    return VerifyArtifact(
        verify_id="verify-stub",
        build_id="build-stub",
        plan_id="plan-stub",
        spec_id="stub-spec",
        test_environment=VerificationEnvironment(),
        criteria_verdicts=[
            CriterionVerification(
                criterion_id="ac-0",
                criterion_text="stub",
                status="passed",
                verification_level="unit",
                mock_policy="not_applicable",
                evidence_summary="stub passed",
            )
        ],
        overall_status="passed",
    )


def _stub_ship_artifact() -> ShipArtifact:
    return ShipArtifact(
        ship_id="ship-stub",
        verify_id="verify-stub",
        build_id="build-stub",
        plan_id="plan-stub",
        spec_id="stub-spec",
        branch_name="main",
        head_sha="000000",
        worktree_clean=True,
        tests_passing=True,
        acceptance_criteria_met=True,
        readiness_summary="stub ready",
        release_notes="stub release",
        rollback_plan="revert stub commit",
        recommended_action="ship",
    )


def _default_stub_runner(stage_name: str) -> StageRunner:
    """Return a stub runner for the given stage that produces a minimal valid artifact."""
    _factories: dict[str, Callable] = {
        "spec_prep": _stub_spec_prep_artifact,
        "plan": _stub_plan_artifact,
        "build": _stub_build_artifact,
        "verify": _stub_verify_artifact,
        "ship": _stub_ship_artifact,
    }

    def runner(run: AutopilotRun, registry: dict[str, Any], guidance: Optional[str] = None) -> Any:
        factory = _factories.get(stage_name)
        if factory is not None:
            return factory()
        raise ValueError(f"No stub runner for unknown stage: {stage_name!r}")

    return runner


# ---------------------------------------------------------------------------
# LinearOrchestrator
# ---------------------------------------------------------------------------


class LinearOrchestrator:
    """Sequences work stages through the autopilot pipeline with gate enforcement.

    The orchestrator is the central state machine wiring Phase 26-29 modules:
    - loader.py (StageRegistryEntry, load_default_registry)
    - run.py (persist, load_run, validate_transition, resume)
    - normalizer.py (GateNormalizer)
    - artifacts.py (GateDecision and all stage artifacts)

    Attributes:
        PIPELINE_START: Name of the first stage in the pipeline.
    """

    PIPELINE_START: str = "spec_prep"

    def __init__(
        self,
        registry: dict[str, StageRegistryEntry],
        runners: dict[str, StageRunner],
        normalizer: Optional[GateNormalizer] = None,
        max_revise_iterations: int = 3,
        gate_runners: Optional[dict[str, Callable[[], GateDecision]]] = None,
    ) -> None:
        """Initialise the orchestrator.

        Args:
            registry: Stage registry from load_default_registry() or custom.
            runners: Map of stage_name -> StageRunner. Missing keys fall back to
                _default_stub_runner(stage_name).
            normalizer: GateNormalizer to use for normalizing protocol artifacts.
                Defaults to GateNormalizer().
            max_revise_iterations: Maximum revise loop iterations per stage before
                setting run.status=failed.
            gate_runners: Optional injectable gate runners keyed by gate_type.
                When provided, the gate runner is called directly (returns GateDecision)
                instead of running stub protocol + normalizer. Useful for testing.
        """
        self._registry = registry
        self._runners = {
            name: runners.get(name, _default_stub_runner(name))
            for name in registry
        }
        self._normalizer = normalizer if normalizer is not None else GateNormalizer()
        self._max_revise = max_revise_iterations
        self._gate_runners = gate_runners or {}
        # Note: build_retry_count is persisted on AutopilotRun, not here.
        # self._build_retry_count removed — use run.build_retry_count instead.
        self._last_raw_artifact: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        run: AutopilotRun,
        artifact_registry: Optional[dict[str, Any]] = None,
    ) -> AutopilotRun:
        """Execute the full pipeline from run.current_stage to completion.

        Sequences stages in topological order following allowed_next links.
        Persists run state after every checkpoint. Stops on block/failure.

        Args:
            run: AutopilotRun instance (status should be "running").
            artifact_registry: Pre-populated artifact registry (used when resuming
                from a paused run). Defaults to {}.

        Returns:
            The updated AutopilotRun with final status.
        """
        # Ensure run is in running state
        if run.status != "running":
            validate_transition(run.status, "running")
            run.status = "running"  # type: ignore[assignment]
        run.updated_at = time.time()

        if artifact_registry is None:
            artifact_registry = {}

        current_stage: Optional[str] = run.current_stage

        while current_stage is not None:
            entry = self._registry.get(current_stage)
            if entry is None:
                run.status = "failed"  # type: ignore[assignment]
                run.failure_reason = f"Unknown stage: {current_stage!r}"
                persist(run)
                return run

            runner = self._runners.get(current_stage, _default_stub_runner(current_stage))

            # SAFE-02: Pre-execution approval boundary.
            # Must fire BEFORE marking in_progress to prevent any runner execution
            # on stages requiring human approval.
            if self._should_pause_for_approval(run, entry):
                run.current_stage = current_stage
                run.updated_at = time.time()
                checkpoint = self._find_stage_checkpoint(run, current_stage)
                checkpoint.status = "blocked"
                validate_transition(run.status, "paused_for_approval")
                run.status = "paused_for_approval"  # type: ignore[assignment]
                persist(run)
                break

            # Update current_stage and mark in_progress
            run.current_stage = current_stage
            run.updated_at = time.time()
            checkpoint = self._find_stage_checkpoint(run, current_stage)
            checkpoint.status = "in_progress"
            checkpoint.started_at = time.time()
            persist(run)

            # ORCH-05: override gate_type for verify based on challenge conditions.
            # If challenge should NOT run, treat verify's gate as "none" so it
            # advances directly to ship without running the challenge protocol.
            gate_type_override: Optional[str] = None
            if current_stage == "verify":
                if not self._should_run_challenge(run):
                    gate_type_override = "none"

            # Run stage with gate loop
            self._run_stage_with_gate(
                run, artifact_registry, current_stage, runner, entry,
                gate_type_override=gate_type_override,
            )

            # If run is no longer running (blocked/failed), stop
            if run.status != "running":
                break

            # SAFE-04: Check for tier promotion after any stage that produces files_changed.
            # Fires if the artifact has files_changed (e.g., BuildArtifact) and spec_target_files
            # are available. Promotion is monotonic — tier only goes up.
            stage_art = artifact_registry.get(current_stage)
            if stage_art is not None:
                actual_files: list[str] = []
                if hasattr(stage_art, "files_changed"):
                    actual_files = list(stage_art.files_changed)
                elif isinstance(stage_art, dict) and "files_changed" in stage_art:
                    actual_files = list(stage_art.get("files_changed", []))
                if actual_files:
                    self._maybe_promote_tier(run, run.spec_target_files, actual_files)

            # VER-04: verify->build retry loop (FM-04: uses inner loop, not outer continue)
            # After verify stage completes, check for retry_build recommendation.
            # If found, re-run build (with revision_guidance) then re-run verify.
            # Capped at 2 retries (3 total build attempts) before escalating.
            # Uses an inner while loop to avoid re-dispatching verify via the outer loop.
            if current_stage == "verify":
                retry_exhausted = False
                while run.status == "running":
                    verify_art = artifact_registry.get("verify")
                    retry_rec: Optional[str] = None
                    if hasattr(verify_art, "retry_recommendation"):
                        retry_rec = verify_art.retry_recommendation
                    elif isinstance(verify_art, dict):
                        retry_rec = verify_art.get("retry_recommendation")

                    if retry_rec != "retry_build":
                        break  # verify passed or no retry needed — exit inner loop

                    # Extract revision guidance
                    rev_guidance: Optional[str] = None
                    if hasattr(verify_art, "revision_guidance"):
                        rev_guidance = verify_art.revision_guidance
                    elif isinstance(verify_art, dict):
                        rev_guidance = verify_art.get("revision_guidance")

                    if run.build_retry_count >= 2:
                        # Max retries exceeded — escalate
                        validate_transition(run.status, "paused_for_approval")
                        run.status = "paused_for_approval"  # type: ignore[assignment]
                        run.failure_reason = (
                            "Verify->build retry loop exhausted (2 retries). "
                            "Manual intervention required."
                        )
                        run.updated_at = time.time()
                        persist(run)
                        retry_exhausted = True
                        break

                    run.build_retry_count += 1
                    persist(run)

                    # Re-run build with revision_guidance
                    build_entry = self._registry.get("build")
                    build_runner = self._runners.get("build", _default_stub_runner("build"))
                    if build_entry is None:
                        break

                    _captured_rev = rev_guidance

                    def _build_with_guidance(
                        _run: AutopilotRun,
                        _reg: dict[str, Any],
                        _guidance: Optional[str] = None,
                        _rev=_captured_rev,
                    ) -> Any:
                        return self._runners.get("build", _default_stub_runner("build"))(_run, _reg, _rev)

                    run.current_stage = "build"
                    run.updated_at = time.time()
                    persist(run)
                    self._run_stage_with_gate(
                        run, artifact_registry, "build", _build_with_guidance, build_entry,
                        gate_type_override=None,
                    )
                    if run.status != "running":
                        break  # build blocked/failed

                    # Re-run verify after build
                    run.current_stage = "verify"
                    run.updated_at = time.time()
                    persist(run)
                    verify_entry = self._registry.get("verify")
                    verify_runner = self._runners.get("verify", _default_stub_runner("verify"))
                    if verify_entry is None:
                        break
                    verify_gate_override: Optional[str] = None
                    if not self._should_run_challenge(run):
                        verify_gate_override = "none"
                    self._run_stage_with_gate(
                        run, artifact_registry, "verify", verify_runner, verify_entry,
                        gate_type_override=verify_gate_override,
                    )
                    # Inner loop continues: re-check verify_art for another retry_build

                if retry_exhausted or run.status != "running":
                    break  # exit outer pipeline loop

                # Verify passed — advance past verify to next stage (ship)
                verify_entry_for_next = self._registry.get("verify")
                if verify_entry_for_next is not None:
                    allowed = verify_entry_for_next.manifest.allowed_next
                    current_stage = allowed[0] if allowed else None
                else:
                    current_stage = None
                continue  # skip the normal next-stage logic below

            # Determine next stage from allowed_next
            allowed_next = entry.manifest.allowed_next
            next_stage: Optional[str] = allowed_next[0] if allowed_next else None

            current_stage = next_stage

        # Mark completed if all stages advanced and we ran off the end
        if run.status == "running":
            validate_transition(run.status, "completed")
            run.status = "completed"  # type: ignore[assignment]
            run.completed_at = time.time()
            run.updated_at = time.time()

        persist(run)
        return run

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _classify_stage(self, run: AutopilotRun, entry: StageRegistryEntry) -> str:
        """Return 'executor', 'council', or 'approval-gated' for this stage/run combo.

        Classification rules (SAFE-01):
        - approval_required=True on manifest -> always approval-gated (unconditional)
        - side_effect_level=external on manifest -> approval-gated
        - default_gate != "none" -> council
        - otherwise -> executor

        Args:
            run: AutopilotRun with tier information.
            entry: StageRegistryEntry with manifest fields.

        Returns:
            One of 'executor', 'council', or 'approval-gated'.
        """
        if entry.manifest.approval_required:
            return "approval-gated"
        if entry.manifest.side_effect_level == "external":
            return "approval-gated"
        if entry.manifest.default_gate != "none":
            return "council"
        return "executor"

    def _should_pause_for_approval(self, run: AutopilotRun, entry: StageRegistryEntry) -> bool:
        """Check whether this stage should pause for human approval before execution.

        Returns False if the stage checkpoint is already "blocked" — this means the stage
        was previously blocked and is now being resumed (the act of calling autopilot_resume
        IS the approval). This prevents infinite re-blocking on resume.

        Args:
            run: AutopilotRun with tier information.
            entry: StageRegistryEntry with manifest fields.

        Returns:
            True if stage should pause for approval before runner fires.
        """
        if self._classify_stage(run, entry) != "approval-gated":
            return False
        # If checkpoint already blocked, approval was granted via resume — skip guard
        checkpoint = self._find_stage_checkpoint(run, entry.manifest.stage_name)
        return checkpoint.status != "blocked"

    def _run_stage_with_gate(
        self,
        run: AutopilotRun,
        artifact_registry: dict[str, Any],
        stage_name: str,
        runner: StageRunner,
        entry: StageRegistryEntry,
        gate_type_override: Optional[str] = None,
    ) -> None:
        """Execute the work stage and gate loop for a single stage.

        Handles advance, revise, and block gate decisions. Persists run after
        every state change. On max revise exceeded, sets run.status=failed.
        On block, sets run.status=paused_for_approval.

        Args:
            run: AutopilotRun being executed.
            artifact_registry: Mutable artifact registry dict.
            stage_name: Name of the stage to run.
            runner: StageRunner callable for this stage.
            entry: StageRegistryEntry providing manifest for this stage.
            gate_type_override: If provided, use this gate_type instead of the
                manifest's default_gate. "none" forces immediate advance (ORCH-05).
        """
        revise_count = 0
        guidance: Optional[str] = None
        checkpoint = self._find_stage_checkpoint(run, stage_name)

        while True:
            # FM-03: On resume after a gate failure, skip the runner if an artifact
            # already exists in the checkpoint. The runner already ran successfully;
            # only the gate needs to be retried.
            if (
                checkpoint.artifact_snapshot is not None
                and checkpoint.status in ("gated", "blocked")
                and guidance is None  # revise loops need re-execution with new guidance
            ):
                artifact = artifact_registry.get(stage_name)
                if artifact is None:
                    # Reconstruct from snapshot if not in registry
                    artifact = checkpoint.artifact_snapshot
                    artifact_registry[stage_name] = artifact
            else:
                # Execute the work stage
                try:
                    artifact = runner(run, artifact_registry, guidance)
                except Exception as exc:
                    # Runner crashed — transition to failed with diagnostic info
                    checkpoint.status = "blocked"
                    checkpoint.completed_at = time.time()
                    run.failure_reason = (
                        f"Stage runner '{stage_name}' raised {type(exc).__name__}: {exc}"
                    )
                    validate_transition(run.status, "failed")
                    run.status = "failed"  # type: ignore[assignment]
                    run.updated_at = time.time()
                    persist(run)
                    return
                artifact_registry[stage_name] = artifact

            # Update checkpoint with artifact snapshot
            checkpoint.status = "gated"
            if hasattr(artifact, "model_dump"):
                checkpoint.artifact_snapshot = artifact.model_dump()
                run.artifact_registry[stage_name] = artifact.model_dump()
            run.updated_at = time.time()
            persist(run)

            # Determine gate type (use override if provided, e.g., ORCH-05 verify skipping challenge)
            gate_type = gate_type_override if gate_type_override is not None else entry.manifest.default_gate

            # No gate — advance immediately
            if gate_type == "none":
                checkpoint.status = "advanced"
                checkpoint.completed_at = time.time()
                run.updated_at = time.time()
                persist(run)
                break

            # Run the gate with retry policy from manifest (SAFE-05)
            try:
                gate_decision, raw_artifact = self._run_gate_with_retry(
                    gate_type, entry.manifest.retry_policy
                )
            except Exception as exc:
                # All retries exhausted — escalate to paused_for_approval
                checkpoint.status = "blocked"
                run.failure_reason = (
                    f"Stage {stage_name!r}: gate {gate_type!r} failed after "
                    f"retry_policy={entry.manifest.retry_policy!r} exhausted. "
                    f"Error: {exc}"
                )
                validate_transition(run.status, "paused_for_approval")
                run.status = "paused_for_approval"  # type: ignore[assignment]
                run.updated_at = time.time()
                persist(run)
                return

            # SAFE-05 SC4: Check for gate-outcome-driven tier promotion
            self._maybe_promote_from_gate(run, gate_type, raw_artifact)

            # Update checkpoint with gate decision
            checkpoint.gate_decision = gate_decision.decision
            checkpoint.gate_session_id = gate_decision.protocol_session_id
            run.updated_at = time.time()

            if gate_decision.decision == "advance":
                checkpoint.status = "advanced"
                checkpoint.completed_at = time.time()
                persist(run)
                break

            elif gate_decision.decision == "revise":
                revise_count += 1
                if revise_count >= self._max_revise:
                    # Max revisions exceeded — fail the run
                    run.failure_reason = (
                        f"Stage {stage_name!r}: max revise iterations "
                        f"({self._max_revise}) exceeded"
                    )
                    validate_transition(run.status, "failed")
                    run.status = "failed"  # type: ignore[assignment]
                    run.updated_at = time.time()
                    persist(run)
                    return
                # Set revision_guidance and loop
                guidance = gate_decision.revision_guidance
                checkpoint.revision_guidance = guidance
                run.updated_at = time.time()
                persist(run)
                # Loop back to re-run the work stage

            elif gate_decision.decision == "block":
                checkpoint.status = "blocked"
                run.updated_at = time.time()
                validate_transition(run.status, "paused_for_approval")
                run.status = "paused_for_approval"  # type: ignore[assignment]
                persist(run)
                return

    def _run_gate(self, gate_type: str) -> GateDecision:
        """Run a gate and return a GateDecision.

        If gate_runners[gate_type] is provided, call it directly.
        Otherwise create a stub protocol artifact and normalize it.

        Args:
            gate_type: The gate type string (e.g., "review_loop", "challenge").

        Returns:
            A normalized GateDecision.
        """
        # Use injected gate runner if available
        if gate_type in self._gate_runners:
            self._last_raw_artifact = None
            return self._gate_runners[gate_type]()

        # Fall back to stub protocol artifact + normalizer
        if gate_type == "review_loop" and ConvergenceResult is not None:
            stub_artifact = ConvergenceResult(
                final_verdict="pass",
                exit_reason="all_verified",
                final_findings=[],
                total_iterations=1,
            )
            self._last_raw_artifact = stub_artifact
            return self._normalizer.normalize("review_loop", stub_artifact)

        if gate_type == "challenge" and ChallengeArtifact is not None:
            stub_artifact = ChallengeArtifact(
                readiness="ready",
                summary="stub challenge gate",
                failure_modes=[],
                next_action="proceed",
            )
            self._last_raw_artifact = stub_artifact
            return self._normalizer.normalize("challenge", stub_artifact)

        # Fallback: produce an advance decision for unknown/unavailable gate types
        self._last_raw_artifact = None
        return GateDecision(
            decision="advance",
            protocol_type="review_loop",
            protocol_session_id="stub-fallback",
            rationale=f"Stub gate advance for gate_type={gate_type!r}",
        )

    def _should_run_challenge(self, run: AutopilotRun) -> bool:
        """Determine whether the challenge gate should run after verify (ORCH-05).

        Returns True if:
        - verify manifest has side_effect_level="external", OR
        - run.tier == 3

        Args:
            run: AutopilotRun with tier information.

        Returns:
            True if challenge gate should be invoked.
        """
        entry = self._registry.get("verify")
        if entry is not None and entry.manifest.side_effect_level == "external":
            return True
        if run.tier >= 3:
            return True
        return False

    def _apply_tier3_promotion(self, run: AutopilotRun, reason: str) -> None:
        """Monotonically promote run to tier 3. No-op if already tier 3. Persists immediately.

        Args:
            run: AutopilotRun whose tier may be promoted.
            reason: Human-readable reason for the promotion (stored in tier_classification_reason).
        """
        if run.tier < 3:
            run.tier = 3
            run.tier_promoted_at = datetime.now(timezone.utc).isoformat()
            run.tier_classification_reason = reason
            run.updated_at = time.time()
            persist(run)

    def _maybe_promote_from_gate(
        self,
        run: AutopilotRun,
        gate_type: str,
        raw_artifact: Any,
    ) -> None:
        """Promote tier if gate output signals challenge not_ready or critical/high review finding.

        Inspects the raw protocol artifact (before normalization) for:
        - ChallengeArtifact with readiness="not_ready" → promote to tier 3
        - ConvergenceResult with a Finding of severity "critical" or "high" → promote to tier 3
        - ReviewArtifact with a Finding of severity "critical" or "high" → promote to tier 3

        Graceful no-op if raw_artifact is None or unrecognized type.

        Args:
            run: AutopilotRun whose tier may be promoted.
            gate_type: The gate type string (used in promotion reason message).
            raw_artifact: The raw protocol artifact before normalization, or None.
        """
        if raw_artifact is None:
            return

        if ChallengeArtifact is not None and isinstance(raw_artifact, ChallengeArtifact):
            if raw_artifact.readiness == "not_ready":
                self._apply_tier3_promotion(
                    run,
                    f"gate {gate_type!r}: challenge readiness=not_ready",
                )
            return

        findings = None
        reason_prefix = f"gate {gate_type!r}"
        if ConvergenceResult is not None and isinstance(raw_artifact, ConvergenceResult):
            findings = raw_artifact.final_findings
        elif ReviewArtifact is not None and isinstance(raw_artifact, ReviewArtifact):
            findings = raw_artifact.findings

        if findings is not None:
            for finding in findings:
                if getattr(finding, "severity", None) in ("critical", "high"):
                    self._apply_tier3_promotion(
                        run,
                        f"{reason_prefix}: review finding severity={finding.severity!r}",
                    )
                    break

    def _run_gate_with_retry(
        self,
        gate_type: str,
        retry_policy: str,
    ) -> tuple[GateDecision, Any]:
        """Run gate with retry according to manifest retry_policy.

        Returns (gate_decision, raw_artifact) where raw_artifact is the protocol
        artifact before normalization (for promotion checks). When using injected
        gate_runners, raw_artifact is None (gate_runners return GateDecision directly).

        retry_policy="none": single attempt, re-raise on exception
        retry_policy="once": one retry on exception
        retry_policy="backend_fallback": try fallback runner if registered, else retry primary once

        Args:
            gate_type: The gate type string (e.g., "review_loop", "challenge").
            retry_policy: One of "none", "once", "backend_fallback".

        Returns:
            Tuple of (GateDecision, raw_artifact).

        Raises:
            Exception: Re-raised from gate runner if all retries are exhausted.
        """
        try:
            result = self._run_gate(gate_type)
            return result, self._last_raw_artifact
        except Exception:
            if retry_policy == "none":
                raise

            # "backend_fallback": try registered fallback runner if available
            if retry_policy == "backend_fallback":
                fallback_key = f"{gate_type}_fallback"
                if fallback_key in self._gate_runners:
                    self._last_raw_artifact = None
                    result = self._gate_runners[fallback_key]()
                    return result, self._last_raw_artifact
                # No fallback registered — fall through to retry primary once

            # "once" (and "backend_fallback" with no fallback): retry primary gate
            result = self._run_gate(gate_type)
            return result, self._last_raw_artifact

    def _maybe_promote_tier(
        self,
        run: AutopilotRun,
        declared_paths: list[str],
        actual_paths: list[str],
    ) -> None:
        """Promote run.tier if undeclared sensitive files are detected (SAFE-04).

        Monotonic operation — tier only increases, never decreases.
        Sets tier_promoted_at to ISO timestamp and persists run if promotion occurs.

        Args:
            run: AutopilotRun whose tier may be promoted.
            declared_paths: Paths declared in the spec (spec_target_files).
            actual_paths: Paths actually touched (e.g., BuildArtifact.files_changed).
        """
        undeclared = detect_undeclared_sensitive_files(declared_paths, actual_paths)
        if undeclared:
            self._apply_tier3_promotion(
                run,
                f"undeclared sensitive files: {undeclared}",
            )

    def _find_stage_checkpoint(
        self,
        run: AutopilotRun,
        stage_name: str,
    ) -> StageCheckpoint:
        """Find or create a StageCheckpoint for the given stage.

        Args:
            run: AutopilotRun containing the stages list.
            stage_name: Stage to find or create checkpoint for.

        Returns:
            Existing or newly created StageCheckpoint (mutates run.stages).
        """
        for checkpoint in run.stages:
            if checkpoint.stage_name == stage_name:
                return checkpoint
        # Create if missing
        new_checkpoint = StageCheckpoint(stage_name=stage_name, status="pending")
        run.stages.append(new_checkpoint)
        return new_checkpoint


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = ["LinearOrchestrator", "StageRunner"]
