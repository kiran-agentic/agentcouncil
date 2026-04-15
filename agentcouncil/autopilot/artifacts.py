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
