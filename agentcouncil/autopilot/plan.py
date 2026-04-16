"""agentcouncil.autopilot.plan -- plan stage runner.

Implements the plan stage: decomposes a SpecPrepArtifact into an ordered
task breakdown with acceptance probes, producing a PlanArtifact ready for
the build stage.

Follows the workflow recipe in workflows/plan/workflow.md:
- Step 1: Parse the spec completely
- Step 2: Identify natural decomposition boundaries
- Step 3: Size and order tasks
- Step 4: Write acceptance probes for each spec criterion
- Step 5: Write execution order and verification strategy
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from agentcouncil.autopilot.artifacts import (
    AcceptanceProbe,
    PlanArtifact,
    PlanTask,
    SpecPrepArtifact,
)
from agentcouncil.autopilot.run import AutopilotRun

__all__ = ["run_plan"]


# ---------------------------------------------------------------------------
# Task decomposition helpers
# ---------------------------------------------------------------------------

# Keywords that indicate data/schema work (should come first in execution order)
_SCHEMA_KEYWORDS = {"schema", "model", "migration", "table", "column", "database", "db"}
# Keywords indicating interface/API work (second priority)
_INTERFACE_KEYWORDS = {"api", "endpoint", "route", "interface", "contract", "protocol"}
# Keywords indicating infrastructure/setup work (early priority)
_INFRA_KEYWORDS = {"config", "setup", "install", "infra", "deploy", "ci", "pipeline"}


def _classify_requirement(req: str) -> str:
    """Classify a requirement into a priority bucket for ordering.

    Returns one of: 'schema', 'interface', 'infra', 'logic', 'test'.
    """
    req_lower = req.lower()

    if any(kw in req_lower for kw in _SCHEMA_KEYWORDS):
        return "schema"
    if any(kw in req_lower for kw in _INTERFACE_KEYWORDS):
        return "interface"
    if any(kw in req_lower for kw in _INFRA_KEYWORDS):
        return "infra"
    if any(kw in req_lower for kw in ("test", "verify", "assert", "check")):
        return "test"
    return "logic"


_PRIORITY_ORDER = {"schema": 0, "infra": 1, "interface": 2, "logic": 3, "test": 4}


def _estimate_complexity(req: str, target_files: list[str]) -> str:
    """Estimate task complexity from requirement text and target files.

    Returns 'small', 'medium', or 'large'.
    """
    # Rough heuristic: more files = larger task
    file_count = len(target_files)
    word_count = len(req.split())

    if file_count <= 1 and word_count < 15:
        return "small"
    if file_count > 3 or word_count > 40:
        return "large"
    return "medium"


def _select_verification_level(
    criterion_text: str,
    research_test_commands: list[str],
) -> str:
    """Choose the appropriate verification level for an acceptance criterion.

    Returns one of: 'static', 'unit', 'integration', 'smoke', 'e2e'.
    """
    crit_lower = criterion_text.lower()

    # E2E indicators
    if any(kw in crit_lower for kw in ("browser", "ui", "page", "click", "render", "e2e")):
        return "e2e"

    # Integration indicators
    if any(kw in crit_lower for kw in (
        "api", "endpoint", "database", "service", "subprocess", "external",
        "persist", "save", "load", "network",
    )):
        return "integration"

    # Smoke indicators
    if any(kw in crit_lower for kw in ("startup", "health", "boot", "connect")):
        return "smoke"

    # Static indicators
    if any(kw in crit_lower for kw in ("type", "lint", "format", "import", "syntax")):
        return "static"

    # Default to unit
    return "unit"


# ---------------------------------------------------------------------------
# Core planning logic
# ---------------------------------------------------------------------------


def _decompose_spec(prep: SpecPrepArtifact) -> tuple[list[PlanTask], list[str]]:
    """Decompose a SpecPrepArtifact into ordered PlanTasks.

    Each requirement becomes a task. Tasks are ordered by classification
    priority (schema > infra > interface > logic > test) and then by
    original order within each bucket.

    Returns (tasks, execution_order).
    """
    spec = prep.finalized_spec
    research = prep.research

    # Distribute target files across requirements proportionally
    # (simple: assign all target files to all tasks, let build refine)
    all_target_files = list(spec.target_files)

    # Build tasks from requirements
    classified: list[tuple[int, str, int, str]] = []  # (priority, category, index, req)
    for i, req in enumerate(spec.requirements):
        category = _classify_requirement(req)
        priority = _PRIORITY_ORDER.get(category, 3)
        classified.append((priority, category, i, req))

    # Sort by priority, preserving original order within same priority
    classified.sort(key=lambda x: (x[0], x[2]))

    tasks: list[PlanTask] = []
    execution_order: list[str] = []
    prev_task_id: Optional[str] = None

    for _, category, orig_idx, req in classified:
        task_id = f"task-{orig_idx + 1:02d}"
        complexity = _estimate_complexity(req, all_target_files)

        # Map acceptance criteria: each task gets criteria from the same index
        # if available, otherwise the requirement itself becomes the criterion
        task_criteria: list[str] = []
        if orig_idx < len(spec.acceptance_criteria):
            task_criteria.append(spec.acceptance_criteria[orig_idx])
        else:
            task_criteria.append(f"Requirement implemented: {req}")

        # Dependencies: sequential within same category for safety
        depends_on = [prev_task_id] if prev_task_id is not None else []

        task = PlanTask(
            task_id=task_id,
            title=_make_task_title(req),
            description=req,
            acceptance_criteria=task_criteria,
            depends_on=depends_on,
            target_files=all_target_files,
            estimated_complexity=complexity,
        )
        tasks.append(task)
        execution_order.append(task_id)
        prev_task_id = task_id

    return tasks, execution_order


def _make_task_title(requirement: str) -> str:
    """Create a short imperative title from a requirement string."""
    # Take first ~60 chars, trim to last word boundary
    title = requirement.strip()
    if len(title) > 60:
        title = title[:60].rsplit(" ", 1)[0]
        if not title.endswith("..."):
            title += "..."
    return title


def _build_acceptance_probes(
    prep: SpecPrepArtifact,
    tasks: list[PlanTask],
) -> list[AcceptanceProbe]:
    """Build AcceptanceProbes mapping each acceptance criterion to tasks.

    Each criterion in spec.acceptance_criteria gets at least one probe.
    """
    spec = prep.finalized_spec
    research = prep.research
    task_ids = [t.task_id for t in tasks]

    probes: list[AcceptanceProbe] = []
    for i, criterion in enumerate(spec.acceptance_criteria):
        criterion_id = f"ac-{i}"
        probe_id = f"probe-{i}"

        verification_level = _select_verification_level(
            criterion, research.test_commands,
        )

        # Determine mock policy: behavior-changing criteria should forbid mocks
        # at integration+ levels
        if verification_level in ("integration", "smoke", "e2e"):
            mock_policy = "forbidden"
        elif verification_level == "static":
            mock_policy = "not_applicable"
        else:
            mock_policy = "forbidden"

        # Command hint from research
        command_hint = research.test_commands[0] if research.test_commands else None

        # Related tasks: find tasks whose acceptance_criteria mention this criterion
        related_task_ids: list[str] = []
        for task in tasks:
            for tc in task.acceptance_criteria:
                if criterion in tc or tc in criterion:
                    related_task_ids.append(task.task_id)
                    break
        # Fallback: relate to the task at the same index position
        if not related_task_ids and i < len(task_ids):
            related_task_ids = [task_ids[i]]

        probe = AcceptanceProbe(
            probe_id=probe_id,
            criterion_id=criterion_id,
            criterion_text=criterion,
            verification_level=verification_level,
            target_behavior=criterion,
            command_hint=command_hint,
            expected_observation=f"Criterion '{criterion}' is satisfied",
            mock_policy=mock_policy,
            related_task_ids=related_task_ids,
            confidence="medium",
        )
        probes.append(probe)

    return probes


def _build_verification_strategy(
    prep: SpecPrepArtifact,
    probes: list[AcceptanceProbe],
) -> str:
    """Build a verification strategy narrative from probes and research."""
    research = prep.research

    parts: list[str] = []

    # Test commands
    if research.test_commands:
        parts.append(f"Test commands: {', '.join(research.test_commands)}.")
    else:
        parts.append("No test infrastructure detected; verify stage will generate probe stubs.")

    # Verification levels summary
    levels = {}
    for p in probes:
        levels[p.verification_level] = levels.get(p.verification_level, 0) + 1
    level_summary = ", ".join(f"{count} {level}" for level, count in sorted(levels.items()))
    parts.append(f"Probes: {level_summary}.")

    # Service requirements
    all_services = set()
    for p in probes:
        all_services.update(p.service_requirements)
    if all_services:
        parts.append(f"Required services: {', '.join(sorted(all_services))}.")

    # Sensitive areas
    if research.sensitive_areas:
        parts.append(
            f"Sensitive areas to watch: {', '.join(research.sensitive_areas[:5])}."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Top-level stage runner
# ---------------------------------------------------------------------------


def run_plan(
    run: AutopilotRun,
    registry: dict[str, Any],
    guidance: Optional[str] = None,
) -> PlanArtifact:
    """Plan stage runner — produces PlanArtifact from SpecPrepArtifact.

    Matches StageRunner callable signature: (run, registry, guidance) -> artifact.

    Implements the planning workflow:
    1. Extract SpecPrepArtifact from registry
    2. Decompose requirements into ordered tasks
    3. Build acceptance probes for each criterion
    4. Assemble PlanArtifact with verification strategy

    When revision guidance is provided (from a gate revise decision), the
    guidance is appended to the verification strategy as additional context
    for the build stage.
    """
    # Extract SpecPrepArtifact from registry
    prep = registry.get("spec_prep")
    if not isinstance(prep, SpecPrepArtifact):
        # Reconstruct from dict if serialized
        if isinstance(prep, dict):
            prep = SpecPrepArtifact(**prep)
        else:
            raise ValueError(
                "Plan stage requires SpecPrepArtifact in registry['spec_prep']. "
                f"Got: {type(prep).__name__}"
            )

    spec = prep.finalized_spec

    # Step 1-3: Decompose spec into ordered tasks
    tasks, execution_order = _decompose_spec(prep)

    # Step 4: Build acceptance probes
    probes = _build_acceptance_probes(prep, tasks)

    # Step 5: Verification strategy
    verification_strategy = _build_verification_strategy(prep, probes)

    # Incorporate revision guidance if provided (gate revise loop)
    if guidance:
        verification_strategy += f" REVISION NOTE: {guidance}"

    plan_id = f"plan-{uuid.uuid4().hex[:8]}"

    return PlanArtifact(
        plan_id=plan_id,
        spec_id=spec.spec_id,
        prep_id=prep.prep_id,
        tasks=tasks,
        execution_order=execution_order,
        verification_strategy=verification_strategy,
        acceptance_probes=probes,
    )
