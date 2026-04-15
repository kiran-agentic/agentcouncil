from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcouncil.autopilot.artifacts import (
    AcceptanceProbe,
    ClarificationPlan,
    CodebaseResearchBrief,
    PlanArtifact,
    PlanTask,
    SpecArtifact,
    SpecPrepArtifact,
    validate_clarification_complete,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_valid_spec(**overrides) -> SpecArtifact:
    defaults = {
        "spec_id": "my-feature",
        "title": "My Feature",
        "objective": "Add the my-feature capability",
        "requirements": ["REQ-01: must work"],
        "acceptance_criteria": ["ac-0: outputs correct result"],
    }
    defaults.update(overrides)
    return SpecArtifact(**defaults)


def _make_valid_research_brief(**overrides) -> CodebaseResearchBrief:
    defaults = {
        "summary": "Found relevant files in agentcouncil/",
        "relevant_files": ["agentcouncil/schemas.py"],
        "confidence": "medium",
    }
    defaults.update(overrides)
    return CodebaseResearchBrief(**defaults)


def _make_valid_clarification_plan(**overrides) -> ClarificationPlan:
    defaults: dict = {
        "blocking_questions": [],
        "user_answers": [],
    }
    defaults.update(overrides)
    return ClarificationPlan(**defaults)


def _make_valid_spec_prep(**overrides) -> SpecPrepArtifact:
    defaults = {
        "prep_id": "prep-001",
        "finalized_spec": _make_valid_spec(),
        "research": _make_valid_research_brief(),
        "clarification": _make_valid_clarification_plan(),
    }
    defaults.update(overrides)
    return SpecPrepArtifact(**defaults)


def _make_valid_plan_task(task_id: str = "task-1", **overrides) -> PlanTask:
    defaults = {
        "task_id": task_id,
        "title": f"Task {task_id}",
        "description": f"Implement {task_id}",
        "acceptance_criteria": ["It works"],
    }
    defaults.update(overrides)
    return PlanTask(**defaults)


def _make_valid_acceptance_probe(probe_id: str = "probe-1", **overrides) -> AcceptanceProbe:
    defaults = {
        "probe_id": probe_id,
        "criterion_id": "ac-0",
        "criterion_text": "outputs correct result",
        "verification_level": "unit",
        "target_behavior": "function returns expected value",
        "expected_observation": "assert result == expected",
    }
    defaults.update(overrides)
    return AcceptanceProbe(**defaults)


def _make_valid_plan_artifact(**overrides) -> PlanArtifact:
    task = _make_valid_plan_task("task-1")
    defaults = {
        "plan_id": "plan-001",
        "spec_id": "my-feature",
        "tasks": [task],
        "execution_order": ["task-1"],
        "verification_strategy": "unit tests with pytest",
    }
    defaults.update(overrides)
    return PlanArtifact(**defaults)


# ---------------------------------------------------------------------------
# SpecArtifact tests
# ---------------------------------------------------------------------------


def test_spec_artifact_valid():
    spec = _make_valid_spec()
    assert spec.spec_id == "my-feature"
    assert spec.title == "My Feature"
    assert len(spec.requirements) == 1
    assert len(spec.acceptance_criteria) == 1
    assert spec.constraints == []
    assert spec.non_goals == []
    assert spec.context is None


def test_spec_artifact_json_roundtrip():
    original = _make_valid_spec(
        constraints=["no breaking changes"],
        non_goals=["GUI"],
        context="existing system",
        target_files=["agentcouncil/foo.py"],
        assumptions=["Python 3.11+"],
        verification_hints=["run pytest"],
    )
    json_str = original.model_dump_json()
    restored = SpecArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_spec_artifact_empty_requirements():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_spec(requirements=[])
    assert "requirements" in str(exc_info.value)


def test_spec_artifact_empty_acceptance_criteria():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_spec(acceptance_criteria=[])
    assert "acceptance_criteria" in str(exc_info.value)


def test_spec_artifact_empty_spec_id():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_spec(spec_id="")
    assert "spec_id" in str(exc_info.value)


def test_spec_artifact_invalid_spec_id_chars():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_spec(spec_id="Spec With Spaces")
    assert "spec_id" in str(exc_info.value)


def test_spec_artifact_invalid_spec_id_uppercase():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_spec(spec_id="MyFeature")
    assert "spec_id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# CodebaseResearchBrief tests
# ---------------------------------------------------------------------------


def test_codebase_research_brief_valid():
    brief = _make_valid_research_brief()
    assert brief.summary == "Found relevant files in agentcouncil/"
    assert brief.confidence == "medium"
    assert brief.relevant_files == ["agentcouncil/schemas.py"]


def test_codebase_research_brief_empty_summary():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_research_brief(summary="")
    assert "summary" in str(exc_info.value)


def test_codebase_research_brief_json_roundtrip():
    from agentcouncil.schemas import SourceRef

    original = _make_valid_research_brief(
        existing_patterns=["BaseModel subclass"],
        likely_target_files=["agentcouncil/autopilot/artifacts.py"],
        test_commands=["python -m pytest tests/"],
        sensitive_areas=["agentcouncil/schemas.py"],
        unknowns=["Performance under load"],
        confidence="high",
        source_refs=[SourceRef(label="main schema", path="agentcouncil/schemas.py")],
    )
    json_str = original.model_dump_json()
    restored = CodebaseResearchBrief.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# ClarificationPlan tests
# ---------------------------------------------------------------------------


def test_clarification_plan_valid():
    # 0 questions
    plan0 = _make_valid_clarification_plan()
    assert plan0.blocking_questions == []

    # 5 questions (max allowed)
    plan5 = _make_valid_clarification_plan(
        blocking_questions=[f"Q{i}" for i in range(5)],
    )
    assert len(plan5.blocking_questions) == 5


def test_clarification_plan_too_many_questions():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_clarification_plan(
            blocking_questions=[f"Q{i}" for i in range(6)],
        )
    assert "blocking_questions" in str(exc_info.value)


def test_clarification_plan_partial_answers():
    # Partial state is VALID during interactive spec prep
    plan = _make_valid_clarification_plan(
        blocking_questions=["Q1", "Q2", "Q3"],
        user_answers=["A1"],  # only 1 of 3 answered
    )
    assert len(plan.blocking_questions) == 3
    assert len(plan.user_answers) == 1


# ---------------------------------------------------------------------------
# validate_clarification_complete tests
# ---------------------------------------------------------------------------


def test_validate_clarification_complete_pass():
    plan = _make_valid_clarification_plan(
        blocking_questions=["Q1", "Q2"],
        user_answers=["A1", "A2"],
    )
    # Should not raise
    validate_clarification_complete(plan)


def test_validate_clarification_complete_fail():
    plan = _make_valid_clarification_plan(
        blocking_questions=["Q1", "Q2", "Q3"],
        user_answers=["A1"],
    )
    with pytest.raises(ValueError) as exc_info:
        validate_clarification_complete(plan)
    assert "user_answers" in str(exc_info.value)


def test_validate_clarification_complete_zero_questions():
    plan = _make_valid_clarification_plan()
    # 0 questions, 0 answers — complete
    validate_clarification_complete(plan)


# ---------------------------------------------------------------------------
# SpecPrepArtifact tests
# ---------------------------------------------------------------------------


def test_spec_prep_artifact_valid():
    prep = _make_valid_spec_prep()
    assert prep.prep_id == "prep-001"
    assert isinstance(prep.finalized_spec, SpecArtifact)
    assert isinstance(prep.research, CodebaseResearchBrief)
    assert isinstance(prep.clarification, ClarificationPlan)
    assert prep.recommended_tier == 2


def test_spec_prep_artifact_empty_prep_id():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_spec_prep(prep_id="")
    assert "prep_id" in str(exc_info.value)


def test_spec_prep_artifact_json_roundtrip():
    original = _make_valid_spec_prep(
        architecture_notes=["use Pydantic BaseModel"],
        conventions_to_follow=["snake_case"],
        decision_preferences=["prefer explicit over implicit"],
        priority_guidance=["P1 first"],
        binding_decisions=["use SourceRef from schemas"],
        advisory_context=["v1.4 ships first"],
        recommended_tier=1,
        escalation_triggers=["any breaking change"],
    )
    json_str = original.model_dump_json()
    restored = SpecPrepArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# PlanTask tests
# ---------------------------------------------------------------------------


def test_plan_task_valid():
    task = _make_valid_plan_task("impl-01")
    assert task.task_id == "impl-01"
    assert task.title == "Task impl-01"
    assert task.estimated_complexity == "medium"
    assert task.depends_on == []
    assert task.target_files == []


def test_plan_task_with_dependencies():
    task = _make_valid_plan_task(
        "impl-02",
        depends_on=["impl-01"],
        target_files=["agentcouncil/foo.py"],
        estimated_complexity="large",
    )
    assert task.depends_on == ["impl-01"]
    assert task.estimated_complexity == "large"


# ---------------------------------------------------------------------------
# AcceptanceProbe tests
# ---------------------------------------------------------------------------


def test_acceptance_probe_valid():
    probe = _make_valid_acceptance_probe()
    assert probe.probe_id == "probe-1"
    assert probe.criterion_id == "ac-0"
    assert probe.verification_level == "unit"
    assert probe.mock_policy == "forbidden"
    assert probe.confidence == "medium"


def test_acceptance_probe_ac_indices():
    # Various ac-N formats are accepted (no format enforcement in model itself)
    for idx in range(5):
        probe = _make_valid_acceptance_probe(
            probe_id=f"p-{idx}",
            criterion_id=f"ac-{idx}",
        )
        assert probe.criterion_id == f"ac-{idx}"


# ---------------------------------------------------------------------------
# PlanArtifact tests
# ---------------------------------------------------------------------------


def test_plan_artifact_valid():
    artifact = _make_valid_plan_artifact()
    assert artifact.plan_id == "plan-001"
    assert len(artifact.tasks) == 1
    assert artifact.execution_order == ["task-1"]


def test_plan_artifact_empty_tasks():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_plan_artifact(tasks=[], execution_order=[])
    assert "tasks" in str(exc_info.value)


def test_plan_artifact_mismatched_execution_order():
    task = _make_valid_plan_task("task-1")
    # execution_order has an extra unknown id
    with pytest.raises(ValidationError) as exc_info:
        PlanArtifact(
            plan_id="plan-x",
            spec_id="my-feature",
            tasks=[task],
            execution_order=["task-1", "task-unknown"],
            verification_strategy="pytest",
        )
    assert "execution_order" in str(exc_info.value)


def test_plan_artifact_duplicate_execution_order():
    task = _make_valid_plan_task("task-1")
    with pytest.raises(ValidationError) as exc_info:
        PlanArtifact(
            plan_id="plan-x",
            spec_id="my-feature",
            tasks=[task],
            execution_order=["task-1", "task-1"],  # duplicate
            verification_strategy="pytest",
        )
    # Duplicate causes length mismatch or set mismatch
    assert exc_info.value is not None


def test_plan_artifact_invalid_depends_on():
    task = _make_valid_plan_task("task-1", depends_on=["task-nonexistent"])
    with pytest.raises(ValidationError) as exc_info:
        PlanArtifact(
            plan_id="plan-x",
            spec_id="my-feature",
            tasks=[task],
            execution_order=["task-1"],
            verification_strategy="pytest",
        )
    assert "depends_on" in str(exc_info.value)


def test_plan_artifact_invalid_probe_task_ref():
    task = _make_valid_plan_task("task-1")
    probe = _make_valid_acceptance_probe(related_task_ids=["task-nonexistent"])
    with pytest.raises(ValidationError) as exc_info:
        PlanArtifact(
            plan_id="plan-x",
            spec_id="my-feature",
            tasks=[task],
            execution_order=["task-1"],
            verification_strategy="pytest",
            acceptance_probes=[probe],
        )
    assert "related_task_ids" in str(exc_info.value)


def test_plan_artifact_json_roundtrip():
    task1 = _make_valid_plan_task("task-1")
    task2 = _make_valid_plan_task("task-2", depends_on=["task-1"], estimated_complexity="large")
    probe = _make_valid_acceptance_probe(
        probe_id="p-0",
        criterion_id="ac-0",
        related_task_ids=["task-2"],
        verification_level="integration",
        mock_policy="allowed",
    )
    original = PlanArtifact(
        plan_id="plan-full",
        spec_id="my-feature",
        prep_id="prep-001",
        tasks=[task1, task2],
        execution_order=["task-1", "task-2"],
        verification_strategy="pytest with integration markers",
        acceptance_probes=[probe],
    )
    json_str = original.model_dump_json()
    restored = PlanArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_plan_artifact_multiple_tasks_valid():
    tasks = [_make_valid_plan_task(f"task-{i}") for i in range(3)]
    # Introduce dependency chain
    tasks[1] = _make_valid_plan_task("task-1-b", depends_on=["task-0"])
    tasks[2] = _make_valid_plan_task("task-2-c", depends_on=["task-0", "task-1-b"])
    tasks[0] = _make_valid_plan_task("task-0")

    artifact = PlanArtifact(
        plan_id="plan-chain",
        spec_id="my-feature",
        tasks=tasks,
        execution_order=["task-0", "task-1-b", "task-2-c"],
        verification_strategy="pytest",
    )
    assert len(artifact.tasks) == 3


def test_plan_artifact_probe_valid_task_ref():
    task = _make_valid_plan_task("task-1")
    probe = _make_valid_acceptance_probe(related_task_ids=["task-1"])  # valid ref
    artifact = PlanArtifact(
        plan_id="plan-ok",
        spec_id="my-feature",
        tasks=[task],
        execution_order=["task-1"],
        verification_strategy="pytest",
        acceptance_probes=[probe],
    )
    assert len(artifact.acceptance_probes) == 1
