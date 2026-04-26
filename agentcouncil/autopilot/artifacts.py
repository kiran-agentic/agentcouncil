from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from agentcouncil.schemas import SourceRef

__all__ = [
    "SpecArtifact",
    "CodebaseResearchBrief",
    "ClarificationPlan",
    "SpecPrepArtifact",
    "PlanTask",
    "AcceptanceProbe",
    "PlanArtifact",
    "validate_clarification_complete",
    # Output-side models (26-02)
    "BuildEvidence",
    "BuildArtifact",
    "VerificationEnvironment",
    "CommandEvidence",
    "ServiceEvidence",
    "CriterionVerification",
    "VerifyArtifact",
    "ShipArtifact",
    "GateDecision",
    "validate_plan_lineage",
    "validate_build_lineage",
    "validate_verify_lineage",
    "validate_ship_lineage",
]


class SpecArtifact(BaseModel):
    """Section 5.1: User intent crystallized into a typed spec contract."""

    spec_id: str
    title: str
    objective: str
    requirements: list[str]
    acceptance_criteria: list[str]
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    context: Optional[str] = None
    target_files: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    verification_hints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_spec_invariants(self) -> SpecArtifact:
        if not self.spec_id:
            raise ValueError("spec_id must be non-empty")
        if not re.fullmatch(r"[a-z0-9-]+", self.spec_id):
            raise ValueError(
                f"spec_id '{self.spec_id}' must match pattern [a-z0-9-]+"
            )
        if not self.requirements:
            raise ValueError("requirements must be non-empty")
        if not self.acceptance_criteria:
            raise ValueError("acceptance_criteria must be non-empty")
        return self


class CodebaseResearchBrief(BaseModel):
    """Section 5.2: Structured codebase research output from the research stage."""

    summary: str
    relevant_files: list[str] = Field(default_factory=list)
    existing_patterns: list[str] = Field(default_factory=list)
    likely_target_files: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    sensitive_areas: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    source_refs: list[SourceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_summary_nonempty(self) -> CodebaseResearchBrief:
        if not self.summary:
            raise ValueError("summary must be non-empty")
        return self


class ClarificationPlan(BaseModel):
    """Section 5.3: Interactive clarification state — partial state is valid during spec prep."""

    blocking_questions: list[str] = Field(default_factory=list)
    user_answers: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    deferred_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_blocking_questions_limit(self) -> ClarificationPlan:
        if len(self.blocking_questions) > 5:
            raise ValueError(
                f"blocking_questions must have at most 5 items, got {len(self.blocking_questions)}"
            )
        return self


def validate_clarification_complete(plan: ClarificationPlan) -> None:
    """Standalone validator: raises ValueError if answers don't match questions count.

    NOT a model_validator — partial state must be representable during interactive spec prep.
    Call this only when the clarification round is considered complete.
    """
    if len(plan.user_answers) != len(plan.blocking_questions):
        raise ValueError(
            f"user_answers length ({len(plan.user_answers)}) must equal "
            f"blocking_questions length ({len(plan.blocking_questions)})"
        )


class SpecPrepArtifact(BaseModel):
    """Section 5.4: Full prep context consumed by the planner."""

    prep_id: str
    finalized_spec: SpecArtifact
    research: CodebaseResearchBrief
    clarification: ClarificationPlan
    architecture_notes: list[str] = Field(default_factory=list)
    conventions_to_follow: list[str] = Field(default_factory=list)
    decision_preferences: list[str] = Field(default_factory=list)
    priority_guidance: list[str] = Field(default_factory=list)
    binding_decisions: list[str] = Field(default_factory=list)
    advisory_context: list[str] = Field(default_factory=list)
    recommended_tier: Literal[1, 2, 3] = 2
    escalation_triggers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_prep_id_nonempty(self) -> SpecPrepArtifact:
        if not self.prep_id:
            raise ValueError("prep_id must be non-empty")
        return self


class PlanTask(BaseModel):
    """Section 5.5: A single atomic task within a plan."""

    task_id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    depends_on: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    estimated_complexity: Literal["small", "medium", "large"] = "medium"


class AcceptanceProbe(BaseModel):
    """Section 5.5: Describes HOW a single acceptance criterion will be verified."""

    probe_id: str
    criterion_id: str  # format: "ac-{index}" zero-indexed
    criterion_text: str
    verification_level: Literal["static", "unit", "integration", "smoke", "e2e"]
    target_behavior: str
    command_hint: Optional[str] = None
    service_requirements: list[str] = Field(default_factory=list)
    expected_observation: str
    mock_policy: Literal["allowed", "forbidden", "not_applicable"] = "forbidden"
    related_task_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class PlanArtifact(BaseModel):
    """Section 5.5: Full execution plan produced by the planner."""

    plan_id: str
    spec_id: str
    prep_id: Optional[str] = None
    tasks: list[PlanTask]
    execution_order: list[str]
    verification_strategy: str
    acceptance_probes: list[AcceptanceProbe] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_plan_invariants(self) -> PlanArtifact:
        if not self.tasks:
            raise ValueError("tasks must be non-empty")

        task_ids = {t.task_id for t in self.tasks}

        # execution_order must cover all tasks exactly (no duplicates, no missing)
        if set(self.execution_order) != task_ids:
            raise ValueError(
                f"execution_order task IDs {set(self.execution_order)} do not match "
                f"task IDs {task_ids}"
            )
        if len(self.execution_order) != len(self.tasks):
            raise ValueError(
                f"execution_order has {len(self.execution_order)} entries but "
                f"tasks has {len(self.tasks)} — duplicates detected"
            )

        # All depends_on references must be valid task_ids
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in task_ids:
                    raise ValueError(
                        f"Task '{task.task_id}' depends_on unknown task_id '{dep}'"
                    )

        # All AcceptanceProbe.related_task_ids must be valid task_ids
        for probe in self.acceptance_probes:
            for ref in probe.related_task_ids:
                if ref not in task_ids:
                    raise ValueError(
                        f"AcceptanceProbe '{probe.probe_id}' references unknown "
                        f"task_id '{ref}' in related_task_ids"
                    )

        return self


# ---------------------------------------------------------------------------
# Output-side models (Section 5.6–5.10) — added in plan 26-02
# ---------------------------------------------------------------------------


class BuildEvidence(BaseModel):
    """Section 5.6: Evidence produced for a single task during the build stage."""

    task_id: str
    files_changed: list[str]
    test_results: Optional[str] = None
    verification_notes: str


class BuildArtifact(BaseModel):
    """Section 5.6: Complete build output for a plan, aggregating task-level evidence."""

    build_id: str
    plan_id: str
    spec_id: str
    evidence: list[BuildEvidence]
    all_tests_passing: bool
    files_changed: list[str]
    commit_shas: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_evidence_nonempty(self) -> "BuildArtifact":
        if not self.evidence:
            raise ValueError("evidence must be non-empty")
        return self


class VerificationEnvironment(BaseModel):
    """Section 5.7: Runtime environment detected and used during the verify stage."""

    project_types: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    dev_server_command: Optional[str] = None
    service_commands: list[str] = Field(default_factory=list)
    health_checks: list[str] = Field(default_factory=list)
    required_env_vars: list[str] = Field(default_factory=list)
    missing_env_vars: list[str] = Field(default_factory=list)
    playwright_available: bool = False
    confidence: Literal["high", "medium", "low"] = "medium"


class CommandEvidence(BaseModel):
    """Section 5.8: Evidence captured from a single command execution."""

    command: str
    cwd: str
    exit_code: int
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""


class ServiceEvidence(BaseModel):
    """Section 5.8: Evidence captured from a service lifecycle during verification."""

    name: str
    start_command: str
    health_check: Optional[str] = None
    port: Optional[int] = None
    status: Literal["started", "failed", "stopped"]
    logs_tail: str = ""


class CriterionVerification(BaseModel):
    """Section 5.8: Verification result for a single acceptance criterion."""

    criterion_id: str
    criterion_text: str
    status: Literal["passed", "failed", "blocked", "skipped"]
    verification_level: Literal["static", "unit", "integration", "smoke", "e2e"]
    mock_policy: Literal["allowed", "forbidden", "not_applicable"]
    evidence_summary: str
    commands: list[CommandEvidence] = Field(default_factory=list)
    services: list[ServiceEvidence] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    failure_diagnosis: Optional[str] = None
    revision_guidance: Optional[str] = None
    skip_reason: Optional[str] = None
    blocker_type: Optional[str] = None


class VerifyArtifact(BaseModel):
    """Section 5.8: Full verification run result covering all acceptance criteria."""

    verify_id: str
    build_id: str
    plan_id: str
    spec_id: str
    test_environment: VerificationEnvironment
    criteria_verdicts: list[CriterionVerification]
    overall_status: Literal["passed", "failed", "blocked"]
    services_started: list[ServiceEvidence] = Field(default_factory=list)
    generated_tests: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    retry_recommendation: Literal["none", "retry_build", "retry_plan", "block"] = "none"
    revision_guidance: Optional[str] = None
    failure_summary: Optional[str] = None

    @model_validator(mode="after")
    def check_verify_invariants(self) -> "VerifyArtifact":
        # (a) skipped without skip_reason
        for cv in self.criteria_verdicts:
            if cv.status == "skipped" and not cv.skip_reason:
                raise ValueError(
                    f"CriterionVerification '{cv.criterion_id}' has status=skipped "
                    "but skip_reason is empty"
                )

        # (b) blocked without blocker_type
        for cv in self.criteria_verdicts:
            if cv.status == "blocked" and not cv.blocker_type:
                raise ValueError(
                    f"CriterionVerification '{cv.criterion_id}' has status=blocked "
                    "but blocker_type is empty"
                )

        # (c) overall_status=passed with any failing/blocked/improperly-skipped criteria
        if self.overall_status == "passed":
            bad_ids = [
                cv.criterion_id
                for cv in self.criteria_verdicts
                if cv.status in ("failed", "blocked")
                or (cv.status == "skipped" and not cv.skip_reason)
            ]
            if bad_ids:
                raise ValueError(
                    f"overall_status=passed but the following criteria are not "
                    f"passed: {bad_ids}"
                )

        # (d) retry_recommendation=retry_build without revision_guidance
        if self.retry_recommendation == "retry_build" and not self.revision_guidance:
            raise ValueError(
                "retry_recommendation=retry_build requires non-empty revision_guidance"
            )

        return self


class ShipArtifact(BaseModel):
    """Section 5.9: Deterministic readiness package produced by the ship stage."""

    ship_id: str
    verify_id: str
    build_id: str
    plan_id: str
    spec_id: str
    branch_name: str
    head_sha: str
    worktree_clean: bool
    tests_passing: bool
    acceptance_criteria_met: bool
    blockers: list[str] = Field(default_factory=list)
    readiness_summary: str
    release_notes: str
    rollback_plan: str
    remaining_risks: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    recommended_action: Literal["ship", "hold", "rollback"]

    @model_validator(mode="after")
    def check_ship_invariants(self) -> "ShipArtifact":
        if self.recommended_action == "ship":
            errors: list[str] = []
            if self.blockers:
                errors.append("blockers must be empty")
            if not self.tests_passing:
                errors.append("tests_passing must be True")
            if not self.acceptance_criteria_met:
                errors.append("acceptance_criteria_met must be True")
            if not self.worktree_clean:
                errors.append("worktree_clean must be True")
            if not self.rollback_plan:
                errors.append("rollback_plan must be non-empty")
            if errors:
                raise ValueError(
                    f"recommended_action=ship violated: {'; '.join(errors)}"
                )

        if self.recommended_action == "hold":
            if not self.remaining_risks and not self.blockers:
                raise ValueError(
                    "recommended_action=hold requires non-empty remaining_risks or blockers"
                )

        return self


class GateDecision(BaseModel):
    """Section 5.10: Normalized gate output — advance, revise, or block."""

    decision: Literal["advance", "revise", "block"]
    protocol_type: Literal["brainstorm", "review", "review_loop", "challenge", "decide"]
    protocol_session_id: str
    rationale: str
    revision_guidance: Optional[str] = None

    @model_validator(mode="after")
    def check_gate_invariants(self) -> "GateDecision":
        if self.decision == "revise" and not self.revision_guidance:
            raise ValueError(
                "decision=revise requires non-empty revision_guidance"
            )
        return self


# ---------------------------------------------------------------------------
# Transition invariant helpers (Section 5.11)
# ---------------------------------------------------------------------------


def validate_plan_lineage(plan: PlanArtifact, spec: SpecArtifact) -> None:
    """Raises ValueError when PlanArtifact.spec_id does not match SpecArtifact.spec_id."""
    if plan.spec_id != spec.spec_id:
        raise ValueError(
            f"PlanArtifact.spec_id={plan.spec_id!r} does not match "
            f"SpecArtifact.spec_id={spec.spec_id!r}"
        )


def validate_build_lineage(build: BuildArtifact, plan: PlanArtifact) -> None:
    """Raises ValueError when BuildArtifact lineage does not match PlanArtifact."""
    if build.plan_id != plan.plan_id:
        raise ValueError(
            f"BuildArtifact.plan_id={build.plan_id!r} does not match "
            f"PlanArtifact.plan_id={plan.plan_id!r}"
        )
    if build.spec_id != plan.spec_id:
        raise ValueError(
            f"BuildArtifact.spec_id={build.spec_id!r} does not match "
            f"PlanArtifact.spec_id={plan.spec_id!r}"
        )


def validate_verify_lineage(verify: VerifyArtifact, build: BuildArtifact) -> None:
    """Raises ValueError when VerifyArtifact lineage does not match BuildArtifact."""
    if verify.build_id != build.build_id:
        raise ValueError(
            f"VerifyArtifact.build_id={verify.build_id!r} does not match "
            f"BuildArtifact.build_id={build.build_id!r}"
        )
    if verify.spec_id != build.spec_id:
        raise ValueError(
            f"VerifyArtifact.spec_id={verify.spec_id!r} does not match "
            f"BuildArtifact.spec_id={build.spec_id!r}"
        )


def validate_ship_lineage(ship: ShipArtifact, verify: VerifyArtifact) -> None:
    """Raises ValueError when ShipArtifact lineage does not match VerifyArtifact."""
    if ship.verify_id != verify.verify_id:
        raise ValueError(
            f"ShipArtifact.verify_id={ship.verify_id!r} does not match "
            f"VerifyArtifact.verify_id={verify.verify_id!r}"
        )
    if ship.spec_id != verify.spec_id:
        raise ValueError(
            f"ShipArtifact.spec_id={ship.spec_id!r} does not match "
            f"VerifyArtifact.spec_id={verify.spec_id!r}"
        )
