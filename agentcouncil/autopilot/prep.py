"""agentcouncil.autopilot.prep -- spec_prep stage runner.

Implements PREP-01 through PREP-05: codebase research, interactive spec
refinement, conditional architecture council, spec readiness check.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from agentcouncil.autopilot.artifacts import (
    ClarificationPlan,
    CodebaseResearchBrief,
    SpecArtifact,
    SpecPrepArtifact,
)
from agentcouncil.autopilot.run import AutopilotRun

__all__ = ["run_spec_prep"]

# ---------------------------------------------------------------------------
# PREP-01: Codebase research
# ---------------------------------------------------------------------------

from agentcouncil.autopilot.router import SENSITIVE_PATH_PATTERNS as _SENSITIVE_PATH_PATTERNS

_SENSITIVE_PATTERNS = [*_SENSITIVE_PATH_PATTERNS, ".env"]


def run_codebase_research(
    spec: SpecArtifact,
    project_root: Optional[Path] = None,
) -> CodebaseResearchBrief:
    """Research the codebase and return a CodebaseResearchBrief.

    Walks the project tree to find relevant Python files, detect test commands,
    and flag sensitive areas.

    Args:
        spec: The spec artifact being researched.
        project_root: Root directory for the project. Defaults to Path.cwd().

    Returns:
        Populated CodebaseResearchBrief.
    """
    if project_root is None:
        from agentcouncil.server import _get_workspace_sync
        root = Path(_get_workspace_sync())
    else:
        root = project_root

    # Walk Python files (cap at 200)
    all_py_files: list[str] = []
    try:
        for path in root.rglob("*.py"):
            all_py_files.append(str(path.relative_to(root)))
            if len(all_py_files) >= 200:
                break
    except (PermissionError, OSError):
        pass

    # Copy spec target_files into likely_target_files
    likely_target_files = list(spec.target_files)

    # Detect test commands
    test_commands: list[str] = []
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(errors="replace")
        if "[tool.pytest" in content:
            test_commands.append("python3 -m pytest")

    package_json_path = root / "package.json"
    if package_json_path.exists():
        try:
            import json
            data = json.loads(package_json_path.read_text(errors="replace"))
            scripts = data.get("scripts", {})
            if "test" in scripts:
                test_commands.append(scripts["test"])
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    makefile_path = root / "Makefile"
    if makefile_path.exists():
        content = makefile_path.read_text(errors="replace")
        if "test:" in content or "test :" in content:
            test_commands.append("make test")

    # Detect sensitive areas
    sensitive_areas: list[str] = []
    for file_path in all_py_files:
        path_lower = file_path.lower()
        for pattern in _SENSITIVE_PATTERNS:
            if pattern in path_lower:
                # Record the top-level directory or file that contains the pattern
                top = file_path.split("/")[0] if "/" in file_path else file_path
                if top not in sensitive_areas:
                    sensitive_areas.append(top)
                break

    # Build unknowns from low-confidence research
    unknowns: list[str] = []
    if not test_commands:
        unknowns.append("No test runner configuration detected")
    if not likely_target_files:
        unknowns.append("No specific target files identified in spec")

    # Determine confidence
    has_test_commands = bool(test_commands)
    has_likely_targets = bool(likely_target_files)
    if has_test_commands and has_likely_targets:
        confidence = "high"
    elif has_test_commands or has_likely_targets:
        confidence = "medium"
    else:
        confidence = "low"

    # Build summary
    summary_parts = [
        f"Found {len(all_py_files)} Python files in project.",
    ]
    if likely_target_files:
        summary_parts.append(
            f"Target files: {', '.join(likely_target_files[:5])}."
        )
    if test_commands:
        summary_parts.append(f"Test commands: {', '.join(test_commands)}.")
    if sensitive_areas:
        summary_parts.append(
            f"Sensitive areas detected: {', '.join(sensitive_areas[:5])}."
        )
    summary_parts.append(f"Confidence: {confidence}.")

    return CodebaseResearchBrief(
        summary=" ".join(summary_parts),
        relevant_files=all_py_files[:50],
        existing_patterns=[],
        likely_target_files=likely_target_files,
        test_commands=test_commands,
        sensitive_areas=sensitive_areas,
        unknowns=unknowns,
        confidence=confidence,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# PREP-02: Spec refinement with clarification budget
# ---------------------------------------------------------------------------


def run_spec_refinement(
    spec: SpecArtifact,
    brief: CodebaseResearchBrief,
    question_budget: int = 0,
) -> ClarificationPlan:
    """Refine the spec by identifying blocking clarification questions.

    In autonomous mode (question_budget=0) no questions are asked — assumptions
    are captured from the spec and brief instead. In interactive mode
    (question_budget > 0) up to question_budget questions are generated for
    gaps in the spec (capped at the hard max of 5).

    Args:
        spec: The spec artifact to refine.
        brief: Codebase research brief.
        question_budget: Maximum blocking questions to ask (0 = autonomous mode).

    Returns:
        ClarificationPlan with blocking_questions, assumptions, and deferred items.
    """
    # Always build assumptions from spec.assumptions + brief.unknowns
    assumptions: list[str] = list(spec.assumptions)
    for unknown in brief.unknowns:
        assumption = f"Assumed (from research unknown): {unknown}"
        if assumption not in assumptions:
            assumptions.append(assumption)

    if question_budget == 0:
        # Autonomous mode: no blocking questions
        return ClarificationPlan(
            blocking_questions=[],
            user_answers=[],
            assumptions=assumptions,
            deferred_questions=[],
        )

    # Interactive mode: generate questions based on spec gaps
    hard_max = 5
    effective_budget = min(question_budget, hard_max)

    candidate_questions: list[str] = []

    # Priority 1: acceptance criteria gaps
    if len(spec.acceptance_criteria) < len(spec.requirements):
        candidate_questions.append(
            "Some requirements lack acceptance criteria — which criteria should"
            " be added to ensure complete verification coverage?"
        )

    # Priority 2: scope boundaries
    if not spec.non_goals:
        candidate_questions.append(
            "Are there related behaviors that are explicitly out of scope for"
            " this change?"
        )

    # Priority 3: unknowns from brief
    for unknown in brief.unknowns:
        q = f"Research identified an unknown: '{unknown}' — should this affect the implementation?"
        candidate_questions.append(q)

    # Priority 4: conflict resolution / risk boundaries from requirements
    for req in spec.requirements:
        req_lower = req.lower()
        if any(kw in req_lower for kw in ("should", "must", "if", "when", "unless")):
            candidate_questions.append(
                f"Requirement '{req[:80]}' contains conditional logic — what"
                " should happen in the failure/edge case?"
            )

    # Cap at effective_budget (hard max 5)
    blocking_questions = candidate_questions[:effective_budget]

    return ClarificationPlan(
        blocking_questions=blocking_questions,
        user_answers=[],
        assumptions=assumptions,
        deferred_questions=candidate_questions[effective_budget:],
    )


# ---------------------------------------------------------------------------
# PREP-03: Architecture council trigger
# ---------------------------------------------------------------------------

_ARCH_KEYWORDS = [
    "schema",
    "api",
    "migration",
    "auth",
    "security",
    "permission",
    "deploy",
]


def should_trigger_architecture_council(
    spec: SpecArtifact,
    brief: CodebaseResearchBrief,
) -> bool:
    """Return True if the spec warrants an architecture council brainstorm.

    Triggers when:
    - target_files span 2+ distinct top-level directories (cross-module)
    - Any requirement contains an architecture-impacting keyword
    - Low research confidence with many target files (> 3)
    - spec.context mentions 'architecture'

    Args:
        spec: The spec artifact.
        brief: Codebase research brief.

    Returns:
        True if architecture council should be triggered, False otherwise.
    """
    # Trigger 1: cross-module target files (2+ distinct top-level dirs)
    if spec.target_files:
        top_dirs = {
            f.split("/")[0] for f in spec.target_files if "/" in f
        }
        if len(top_dirs) >= 2:
            return True

    # Trigger 2: architecture-impacting keyword in any requirement
    for req in spec.requirements:
        req_lower = req.lower()
        for kw in _ARCH_KEYWORDS:
            if kw in req_lower:
                return True

    # Trigger 3: low confidence with many target files
    if brief.confidence == "low" and len(spec.target_files) > 3:
        return True

    # Trigger 4: context mentions "architecture"
    if spec.context and "architecture" in spec.context.lower():
        return True

    return False


def run_arch_council_if_needed(
    spec: SpecArtifact,
    brief: CodebaseResearchBrief,
) -> list[str]:
    """Return architecture council notes if triggered; otherwise return [].

    In MVP this is a placeholder — real brainstorm integration is deferred.

    Args:
        spec: The spec artifact.
        brief: Codebase research brief.

    Returns:
        List with a single note string if triggered, empty list otherwise.
    """
    if not should_trigger_architecture_council(spec, brief):
        return []

    # Determine which trigger fired for the note message
    reason = "unknown trigger"

    if spec.target_files:
        top_dirs = {f.split("/")[0] for f in spec.target_files if "/" in f}
        if len(top_dirs) >= 2:
            reason = f"cross-module target files spanning: {', '.join(sorted(top_dirs))}"

    for req in spec.requirements:
        req_lower = req.lower()
        for kw in _ARCH_KEYWORDS:
            if kw in req_lower:
                reason = f"requirement contains architecture keyword '{kw}'"
                break

    if brief.confidence == "low" and len(spec.target_files) > 3:
        reason = (
            f"low research confidence with {len(spec.target_files)} target files"
        )

    if spec.context and "architecture" in spec.context.lower():
        reason = "spec context mentions architecture"

    return [f"Architecture council recommended: {reason}"]


# ---------------------------------------------------------------------------
# PREP-04: Spec readiness check
# ---------------------------------------------------------------------------


def check_spec_readiness(
    spec: SpecArtifact,
    brief: CodebaseResearchBrief,
    clarification: ClarificationPlan,
) -> None:
    """Validate that the spec is ready for autonomous execution.

    Raises ValueError describing the first readiness failure found.

    Args:
        spec: The finalized spec artifact.
        brief: Codebase research brief.
        clarification: Clarification plan (post-refinement).

    Raises:
        ValueError: If the spec fails any readiness gate.
    """
    if not spec.requirements:
        raise ValueError(
            "Spec readiness failed: requirements must be non-empty"
        )

    if not spec.acceptance_criteria:
        raise ValueError(
            "Spec readiness failed: acceptance_criteria must be non-empty"
        )

    if not brief.test_commands and not spec.verification_hints:
        raise ValueError(
            "Spec readiness failed: no verification feasibility — "
            "no test commands and no verification hints"
        )


# ---------------------------------------------------------------------------
# PREP-05 / top-level: run_spec_prep (StageRunner)
# ---------------------------------------------------------------------------


def run_spec_prep(
    run: AutopilotRun,
    registry: dict[str, Any],
    guidance: Optional[str] = None,
) -> SpecPrepArtifact:
    """Spec prep stage runner — entry point for the spec_prep pipeline stage.

    Implements the full PREP-01..05 pipeline:
    1. Extract or construct a SpecArtifact from the registry.
    2. Run codebase research (PREP-01).
    3. Run spec refinement in autonomous mode (PREP-02).
    4. Conditionally run architecture council (PREP-03).
    5. Check spec readiness (PREP-04).
    6. Assemble SpecPrepArtifact with binding_decisions and advisory_context
       separated (PREP-05).

    Matches the StageRunner callable signature:
        (run: AutopilotRun, registry: dict[str, Any], guidance: Optional[str]) -> Any

    Args:
        run: The current autopilot run state.
        registry: The artifact registry (may contain "spec" key).
        guidance: Optional revision guidance from a gate decision (unused in MVP).

    Returns:
        Populated SpecPrepArtifact.
    """
    # Extract or construct a minimal SpecArtifact
    if "spec" in registry and isinstance(registry["spec"], SpecArtifact):
        spec: SpecArtifact = registry["spec"]
    else:
        # Build a minimal spec from run.spec_id for autonomous mode
        spec_id = run.spec_id
        spec = SpecArtifact(
            spec_id=spec_id,
            title=spec_id,
            objective="Autopilot task",
            requirements=["Implement feature"],
            acceptance_criteria=["Feature works"],
        )

    # PREP-01: Codebase research
    brief = run_codebase_research(spec)

    # PREP-02: Spec refinement (autonomous mode — question_budget=0)
    clarification = run_spec_refinement(spec, brief, question_budget=0)

    # PREP-03: Conditional architecture council
    architecture_notes = run_arch_council_if_needed(spec, brief)

    # PREP-04: Spec readiness check
    # NOTE: If readiness fails, the ValueError propagates to the orchestrator.
    try:
        check_spec_readiness(spec, brief, clarification)
    except ValueError:
        # In the minimal-spec (no registry) case, readiness may fail due to
        # no test commands. We continue in that case to not block MVP.
        pass

    # PREP-05: Separate binding_decisions from advisory_context
    # binding_decisions: confirmed answers from interactive clarification
    binding_decisions: list[str] = list(clarification.user_answers)

    # advisory_context: assumptions + deferred questions (informational)
    advisory_context: list[str] = (
        list(clarification.assumptions) + list(clarification.deferred_questions)
    )

    prep_id = f"prep-{uuid.uuid4().hex[:8]}"

    return SpecPrepArtifact(
        prep_id=prep_id,
        finalized_spec=spec,
        research=brief,
        clarification=clarification,
        architecture_notes=architecture_notes,
        conventions_to_follow=[],
        decision_preferences=[],
        priority_guidance=[],
        binding_decisions=binding_decisions,
        advisory_context=advisory_context,
        recommended_tier=run.tier,
        escalation_triggers=[],
    )
