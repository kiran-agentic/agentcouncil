from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcouncil.autopilot.artifacts import (
    AcceptanceProbe,
    BuildArtifact,
    BuildEvidence,
    ClarificationPlan,
    CodebaseResearchBrief,
    CommandEvidence,
    CriterionVerification,
    GateDecision,
    PlanArtifact,
    PlanTask,
    ServiceEvidence,
    ShipArtifact,
    SpecArtifact,
    SpecPrepArtifact,
    VerificationEnvironment,
    VerifyArtifact,
    validate_build_lineage,
    validate_clarification_complete,
    validate_plan_lineage,
    validate_ship_lineage,
    validate_verify_lineage,
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


# ---------------------------------------------------------------------------
# Output-side model helper factories (plan 26-02)
# ---------------------------------------------------------------------------


def _make_valid_build_evidence(**overrides) -> BuildEvidence:
    defaults = {
        "task_id": "task-01",
        "files_changed": ["src/main.py"],
        "verification_notes": "Tests pass",
    }
    defaults.update(overrides)
    return BuildEvidence(**defaults)


def _make_valid_build(**overrides) -> BuildArtifact:
    defaults = {
        "build_id": "build-001",
        "plan_id": "plan-001",
        "spec_id": "spec-test",
        "evidence": [_make_valid_build_evidence()],
        "all_tests_passing": True,
        "files_changed": ["src/main.py"],
    }
    defaults.update(overrides)
    return BuildArtifact(**defaults)


def _make_valid_command_evidence(**overrides) -> CommandEvidence:
    defaults = {
        "command": "pytest",
        "cwd": "/app",
        "exit_code": 0,
        "duration_seconds": 1.5,
    }
    defaults.update(overrides)
    return CommandEvidence(**defaults)


def _make_valid_service_evidence(**overrides) -> ServiceEvidence:
    defaults = {
        "name": "postgres",
        "start_command": "docker compose up -d db",
        "status": "started",
    }
    defaults.update(overrides)
    return ServiceEvidence(**defaults)


def _make_valid_criterion_verification(**overrides) -> CriterionVerification:
    defaults = {
        "criterion_id": "ac-0",
        "criterion_text": "Tests pass",
        "status": "passed",
        "verification_level": "unit",
        "mock_policy": "forbidden",
        "evidence_summary": "All tests green",
    }
    defaults.update(overrides)
    return CriterionVerification(**defaults)


def _make_valid_verify(**overrides) -> VerifyArtifact:
    defaults = {
        "verify_id": "verify-001",
        "build_id": "build-001",
        "plan_id": "plan-001",
        "spec_id": "spec-test",
        "test_environment": VerificationEnvironment(),
        "criteria_verdicts": [_make_valid_criterion_verification()],
        "overall_status": "passed",
    }
    defaults.update(overrides)
    return VerifyArtifact(**defaults)


def _make_valid_ship(**overrides) -> ShipArtifact:
    defaults = {
        "ship_id": "ship-001",
        "verify_id": "verify-001",
        "build_id": "build-001",
        "plan_id": "plan-001",
        "spec_id": "spec-test",
        "branch_name": "feat/test",
        "head_sha": "abc123",
        "worktree_clean": True,
        "tests_passing": True,
        "acceptance_criteria_met": True,
        "readiness_summary": "Ready",
        "release_notes": "Initial",
        "rollback_plan": "git revert HEAD",
        "recommended_action": "ship",
    }
    defaults.update(overrides)
    return ShipArtifact(**defaults)


def _make_valid_gate_decision(**overrides) -> GateDecision:
    defaults = {
        "decision": "advance",
        "protocol_type": "review",
        "protocol_session_id": "sess-001",
        "rationale": "All clear",
    }
    defaults.update(overrides)
    return GateDecision(**defaults)


# ---------------------------------------------------------------------------
# BuildEvidence tests
# ---------------------------------------------------------------------------


def test_build_evidence_valid():
    ev = _make_valid_build_evidence()
    assert ev.task_id == "task-01"
    assert ev.files_changed == ["src/main.py"]
    assert ev.verification_notes == "Tests pass"
    assert ev.test_results is None


# ---------------------------------------------------------------------------
# BuildArtifact tests
# ---------------------------------------------------------------------------


def test_build_artifact_valid():
    build = _make_valid_build()
    assert build.build_id == "build-001"
    assert len(build.evidence) == 1
    assert build.all_tests_passing is True
    assert build.commit_shas == []


def test_build_artifact_empty_evidence():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_build(evidence=[])
    assert "evidence" in str(exc_info.value)


def test_build_artifact_json_roundtrip():
    original = _make_valid_build(
        commit_shas=["abc123", "def456"],
        evidence=[
            _make_valid_build_evidence(task_id="task-01", test_results="3 passed"),
            _make_valid_build_evidence(task_id="task-02", files_changed=["src/b.py"]),
        ],
    )
    json_str = original.model_dump_json()
    restored = BuildArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# VerificationEnvironment tests
# ---------------------------------------------------------------------------


def test_verification_environment_defaults():
    env = VerificationEnvironment()
    assert env.project_types == []
    assert env.test_commands == []
    assert env.dev_server_command is None
    assert env.playwright_available is False
    assert env.confidence == "medium"


# ---------------------------------------------------------------------------
# CommandEvidence tests
# ---------------------------------------------------------------------------


def test_command_evidence_valid():
    cmd = _make_valid_command_evidence()
    assert cmd.command == "pytest"
    assert cmd.cwd == "/app"
    assert cmd.exit_code == 0
    assert cmd.duration_seconds == 1.5
    assert cmd.stdout_tail == ""
    assert cmd.stderr_tail == ""


# ---------------------------------------------------------------------------
# ServiceEvidence tests
# ---------------------------------------------------------------------------


def test_service_evidence_valid():
    svc = _make_valid_service_evidence()
    assert svc.name == "postgres"
    assert svc.start_command == "docker compose up -d db"
    assert svc.status == "started"
    assert svc.health_check is None
    assert svc.port is None
    assert svc.logs_tail == ""


# ---------------------------------------------------------------------------
# CriterionVerification tests
# ---------------------------------------------------------------------------


def test_criterion_verification_passed():
    cv = _make_valid_criterion_verification()
    assert cv.criterion_id == "ac-0"
    assert cv.status == "passed"
    assert cv.verification_level == "unit"
    assert cv.mock_policy == "forbidden"


# ---------------------------------------------------------------------------
# VerifyArtifact tests
# ---------------------------------------------------------------------------


def test_verify_artifact_all_passed():
    verify = _make_valid_verify()
    assert verify.verify_id == "verify-001"
    assert verify.overall_status == "passed"
    assert len(verify.criteria_verdicts) == 1


def test_verify_artifact_passed_with_failed_criterion():
    cv = _make_valid_criterion_verification(status="failed", failure_diagnosis="assertion error")
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_verify(criteria_verdicts=[cv], overall_status="passed")
    assert "passed" in str(exc_info.value) or "ac-0" in str(exc_info.value)


def test_verify_artifact_passed_with_blocked_criterion():
    cv = _make_valid_criterion_verification(status="blocked", blocker_type="env-missing")
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_verify(criteria_verdicts=[cv], overall_status="passed")
    assert "passed" in str(exc_info.value) or "ac-0" in str(exc_info.value)


def test_verify_artifact_skipped_without_reason():
    cv = _make_valid_criterion_verification(status="skipped")  # no skip_reason
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_verify(criteria_verdicts=[cv], overall_status="failed")
    assert "skip_reason" in str(exc_info.value) or "skipped" in str(exc_info.value)


def test_verify_artifact_skipped_with_reason():
    cv = _make_valid_criterion_verification(status="skipped", skip_reason="not applicable for this build")
    # overall_status=failed is fine when a criterion is skipped-with-reason
    verify = _make_valid_verify(criteria_verdicts=[cv], overall_status="failed")
    assert verify.overall_status == "failed"
    assert verify.criteria_verdicts[0].status == "skipped"


def test_verify_artifact_blocked_without_blocker_type():
    cv = _make_valid_criterion_verification(status="blocked")  # no blocker_type
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_verify(criteria_verdicts=[cv], overall_status="blocked")
    assert "blocker_type" in str(exc_info.value) or "blocked" in str(exc_info.value)


def test_verify_artifact_retry_build_without_guidance():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_verify(
            overall_status="failed",
            retry_recommendation="retry_build",
            # revision_guidance intentionally omitted
        )
    assert "revision_guidance" in str(exc_info.value) or "retry_build" in str(exc_info.value)


def test_verify_artifact_json_roundtrip():
    cmd = _make_valid_command_evidence(stdout_tail="3 passed", duration_seconds=2.3)
    svc = _make_valid_service_evidence(port=5432, health_check="pg_isready")
    cv = _make_valid_criterion_verification(
        commands=[cmd],
        services=[svc],
        artifacts=["coverage.xml"],
    )
    original = VerifyArtifact(
        verify_id="verify-json",
        build_id="build-001",
        plan_id="plan-001",
        spec_id="spec-test",
        test_environment=VerificationEnvironment(
            project_types=["python"],
            test_commands=["pytest"],
            playwright_available=True,
        ),
        criteria_verdicts=[cv],
        overall_status="passed",
        generated_tests=["tests/test_new.py"],
        coverage_gaps=["edge case X"],
    )
    json_str = original.model_dump_json()
    restored = VerifyArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# ShipArtifact tests
# ---------------------------------------------------------------------------


def test_ship_artifact_ship_valid():
    ship = _make_valid_ship()
    assert ship.ship_id == "ship-001"
    assert ship.recommended_action == "ship"
    assert ship.tests_passing is True


def test_ship_artifact_ship_with_blockers():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_ship(blockers=["unresolved security issue"])
    assert "blockers" in str(exc_info.value)


def test_ship_artifact_ship_tests_not_passing():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_ship(tests_passing=False)
    assert "tests_passing" in str(exc_info.value)


def test_ship_artifact_ship_no_rollback():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_ship(rollback_plan="")
    assert "rollback_plan" in str(exc_info.value)


def test_ship_artifact_hold_valid():
    ship = _make_valid_ship(
        recommended_action="hold",
        remaining_risks=["untested path under high load"],
    )
    assert ship.recommended_action == "hold"
    assert len(ship.remaining_risks) == 1


def test_ship_artifact_hold_no_reasons():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_ship(
            recommended_action="hold",
            remaining_risks=[],
            blockers=[],
        )
    assert "hold" in str(exc_info.value) or "remaining_risks" in str(exc_info.value)


def test_ship_artifact_json_roundtrip():
    original = _make_valid_ship(
        remaining_risks=["minor UX issue"],
        evidence_refs=["verify-001", "build-001"],
        commit_shas=["abc123"],
    )
    json_str = original.model_dump_json()
    restored = ShipArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# GateDecision tests
# ---------------------------------------------------------------------------


def test_gate_decision_advance_valid():
    gate = _make_valid_gate_decision()
    assert gate.decision == "advance"
    assert gate.protocol_type == "review"
    assert gate.revision_guidance is None


def test_gate_decision_revise_without_guidance():
    with pytest.raises(ValidationError) as exc_info:
        _make_valid_gate_decision(decision="revise")
    assert "revision_guidance" in str(exc_info.value) or "revise" in str(exc_info.value)


def test_gate_decision_revise_with_guidance():
    gate = _make_valid_gate_decision(
        decision="revise",
        revision_guidance="Address the auth bypass discovered in review",
    )
    assert gate.decision == "revise"
    assert gate.revision_guidance is not None


def test_gate_decision_json_roundtrip():
    original = _make_valid_gate_decision(
        decision="block",
        protocol_type="challenge",
        rationale="Critical security flaw found",
    )
    json_str = original.model_dump_json()
    restored = GateDecision.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# Transition invariant helper tests
# ---------------------------------------------------------------------------


def test_validate_plan_lineage_match():
    spec = _make_valid_spec()
    plan = _make_valid_plan_artifact(spec_id="my-feature")
    # Should not raise
    validate_plan_lineage(plan, spec)


def test_validate_plan_lineage_mismatch():
    spec = _make_valid_spec(spec_id="spec-a")
    plan = _make_valid_plan_artifact(spec_id="spec-b")
    with pytest.raises(ValueError) as exc_info:
        validate_plan_lineage(plan, spec)
    assert "spec-b" in str(exc_info.value)
    assert "spec-a" in str(exc_info.value)


def test_validate_build_lineage_match():
    plan = _make_valid_plan_artifact(plan_id="plan-001", spec_id="spec-test")
    build = _make_valid_build(plan_id="plan-001", spec_id="spec-test")
    # Should not raise
    validate_build_lineage(build, plan)


def test_validate_build_lineage_plan_mismatch():
    plan = _make_valid_plan_artifact(plan_id="plan-001", spec_id="spec-test")
    build = _make_valid_build(plan_id="plan-WRONG", spec_id="spec-test")
    with pytest.raises(ValueError) as exc_info:
        validate_build_lineage(build, plan)
    assert "plan-WRONG" in str(exc_info.value)
    assert "plan-001" in str(exc_info.value)


def test_validate_build_lineage_spec_mismatch():
    plan = _make_valid_plan_artifact(plan_id="plan-001", spec_id="spec-test")
    build = _make_valid_build(plan_id="plan-001", spec_id="spec-WRONG")
    with pytest.raises(ValueError) as exc_info:
        validate_build_lineage(build, plan)
    assert "spec-WRONG" in str(exc_info.value)
    assert "spec-test" in str(exc_info.value)


def test_validate_verify_lineage_match():
    build = _make_valid_build(build_id="build-001", spec_id="spec-test")
    verify = _make_valid_verify(build_id="build-001", spec_id="spec-test")
    # Should not raise
    validate_verify_lineage(verify, build)


def test_validate_verify_lineage_mismatch():
    build = _make_valid_build(build_id="build-001", spec_id="spec-test")
    verify = _make_valid_verify(build_id="build-WRONG", spec_id="spec-test")
    with pytest.raises(ValueError) as exc_info:
        validate_verify_lineage(verify, build)
    assert "build-WRONG" in str(exc_info.value)
    assert "build-001" in str(exc_info.value)


def test_validate_ship_lineage_match():
    verify = _make_valid_verify(verify_id="verify-001", spec_id="spec-test")
    ship = _make_valid_ship(verify_id="verify-001", spec_id="spec-test")
    # Should not raise
    validate_ship_lineage(ship, verify)


def test_validate_ship_lineage_mismatch():
    verify = _make_valid_verify(verify_id="verify-001", spec_id="spec-test")
    ship = _make_valid_ship(verify_id="verify-WRONG", spec_id="spec-test")
    with pytest.raises(ValueError) as exc_info:
        validate_ship_lineage(ship, verify)
    assert "verify-WRONG" in str(exc_info.value)
    assert "verify-001" in str(exc_info.value)
