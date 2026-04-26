"""Tests for agentcouncil.autopilot.prep — spec_prep stage runner.

Covers:
- PREP-01: Codebase research (run_codebase_research)
- PREP-02: Spec refinement with clarification budget (run_spec_refinement)
- PREP-03: Architecture council trigger (should_trigger_architecture_council)
- PREP-04: Spec readiness check (check_spec_readiness)
- PREP-05: binding_decisions and advisory_context separation
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcouncil.autopilot.artifacts import (
    ClarificationPlan,
    CodebaseResearchBrief,
    SpecArtifact,
    SpecPrepArtifact,
)
from agentcouncil.autopilot.prep import (
    check_spec_readiness,
    run_arch_council_if_needed,
    run_codebase_research,
    run_spec_prep,
    run_spec_refinement,
    should_trigger_architecture_council,
)
from agentcouncil.autopilot.run import AutopilotRun


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_spec(
    spec_id: str = "test-spec",
    requirements: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    target_files: list[str] | None = None,
    context: str | None = None,
    assumptions: list[str] | None = None,
    verification_hints: list[str] | None = None,
) -> SpecArtifact:
    return SpecArtifact(
        spec_id=spec_id,
        title="Test Spec",
        objective="Test objective",
        requirements=requirements or ["Implement feature X"],
        acceptance_criteria=acceptance_criteria or ["Feature X works correctly"],
        target_files=target_files or [],
        context=context,
        assumptions=assumptions or [],
        verification_hints=verification_hints or [],
    )


def _make_brief(
    summary: str = "Found some files",
    relevant_files: list[str] | None = None,
    likely_target_files: list[str] | None = None,
    test_commands: list[str] | None = None,
    unknowns: list[str] | None = None,
    confidence: str = "medium",
) -> CodebaseResearchBrief:
    return CodebaseResearchBrief(
        summary=summary,
        relevant_files=relevant_files or [],
        likely_target_files=likely_target_files or [],
        test_commands=test_commands or [],
        unknowns=unknowns or [],
        confidence=confidence,  # type: ignore[arg-type]
    )


def _make_run(spec_id: str = "test-spec") -> AutopilotRun:
    return AutopilotRun(
        run_id="run-test123",
        spec_id=spec_id,
        status="running",
        current_stage="spec_prep",
        tier=2,
        stages=[],
        artifact_registry={},
        started_at=0.0,
        updated_at=0.0,
    )


# ---------------------------------------------------------------------------
# Task 1: run_codebase_research
# ---------------------------------------------------------------------------


class TestCodebaseResearch:
    def test_returns_codebase_research_brief_with_nonempty_summary(self, tmp_path):
        """run_codebase_research returns CodebaseResearchBrief with non-empty summary."""
        spec = _make_spec()
        brief = run_codebase_research(spec, project_root=tmp_path)
        assert isinstance(brief, CodebaseResearchBrief)
        assert brief.summary, "summary must be non-empty"

    def test_includes_target_files_in_likely_target_files(self, tmp_path):
        """run_codebase_research with target_files includes them in likely_target_files."""
        spec = _make_spec(target_files=["src/auth.py"])
        brief = run_codebase_research(spec, project_root=tmp_path)
        assert "src/auth.py" in brief.likely_target_files

    def test_discovers_pytest_test_command(self, tmp_path):
        """run_codebase_research detects pytest from pyproject.toml [tool.pytest]."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
        spec = _make_spec()
        brief = run_codebase_research(spec, project_root=tmp_path)
        assert "python3 -m pytest" in brief.test_commands

    def test_discovers_typescript_files_and_package_test_command(self, tmp_path):
        """run_codebase_research is manifest-driven, not Python-only."""
        src = tmp_path / "apps/jarvis-voice/src"
        src.mkdir(parents=True)
        (src / "VoiceScreen.tsx").write_text("export function VoiceScreen() { return null }\n")
        (tmp_path / "package.json").write_text(
            '{"scripts":{"test":"vitest run","lint":"eslint ."}}\n'
        )
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions":{}}\n')

        spec = _make_spec(target_files=["apps/jarvis-voice/src/VoiceScreen.tsx"])
        brief = run_codebase_research(spec, project_root=tmp_path)

        assert "apps/jarvis-voice/src/VoiceScreen.tsx" in brief.relevant_files
        assert "vitest run" in brief.test_commands
        assert any("tsconfig.json" in pattern for pattern in brief.existing_patterns)

    def test_no_test_commands_when_no_config(self, tmp_path):
        """run_codebase_research returns empty test_commands when no config present."""
        spec = _make_spec()
        brief = run_codebase_research(spec, project_root=tmp_path)
        assert brief.test_commands == []

    def test_confidence_high_when_both_test_commands_and_target_files(self, tmp_path):
        """Confidence is high when test_commands AND likely_target_files are both populated."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
        spec = _make_spec(target_files=["src/feature.py"])
        brief = run_codebase_research(spec, project_root=tmp_path)
        assert brief.confidence == "high"

    def test_confidence_medium_when_only_one_populated(self, tmp_path):
        """Confidence is medium when only one of test_commands/likely_target_files is populated."""
        spec = _make_spec(target_files=["src/feature.py"])
        brief = run_codebase_research(spec, project_root=tmp_path)
        # No pyproject.toml → test_commands empty, but target_files populated → medium
        assert brief.confidence == "medium"

    def test_confidence_low_when_neither_populated(self, tmp_path):
        """Confidence is low when both test_commands and likely_target_files are empty."""
        spec = _make_spec(target_files=[])
        brief = run_codebase_research(spec, project_root=tmp_path)
        assert brief.confidence == "low"

    def test_detects_sensitive_areas(self, tmp_path):
        """run_codebase_research detects sensitive file patterns."""
        auth_dir = tmp_path / "auth"
        auth_dir.mkdir()
        (auth_dir / "login.py").write_text("# auth code\n")
        spec = _make_spec()
        brief = run_codebase_research(spec, project_root=tmp_path)
        # Should detect auth/ as a sensitive area
        assert any("auth" in area for area in brief.sensitive_areas)


# ---------------------------------------------------------------------------
# Task 2: ClarificationPlan — hard max 5 blocking questions
# ---------------------------------------------------------------------------


class TestClarificationBudget:
    def test_clarification_plan_with_6_questions_raises_validation_error(self):
        """ClarificationPlan with 6 blocking_questions raises ValidationError (hard max 5)."""
        with pytest.raises(ValidationError):
            ClarificationPlan(
                blocking_questions=["q1", "q2", "q3", "q4", "q5", "q6"]
            )

    def test_clarification_plan_with_5_questions_succeeds(self):
        """ClarificationPlan with exactly 5 blocking_questions is valid."""
        plan = ClarificationPlan(
            blocking_questions=["q1", "q2", "q3", "q4", "q5"]
        )
        assert len(plan.blocking_questions) == 5


# ---------------------------------------------------------------------------
# Task 3: run_spec_refinement
# ---------------------------------------------------------------------------


class TestSpecRefinement:
    def test_autonomous_mode_returns_zero_blocking_questions(self, tmp_path):
        """run_spec_refinement with question_budget=0 returns 0 blocking_questions."""
        spec = _make_spec()
        brief = _make_brief()
        clarification = run_spec_refinement(spec, brief, question_budget=0)
        assert len(clarification.blocking_questions) == 0

    def test_interactive_mode_respects_question_budget(self, tmp_path):
        """run_spec_refinement with question_budget=3 returns <= 3 blocking_questions."""
        spec = _make_spec(
            requirements=["Req 1", "Req 2", "Req 3"],
            acceptance_criteria=["Criterion 1"],
        )
        brief = _make_brief(unknowns=["Unknown 1", "Unknown 2", "Unknown 3", "Unknown 4"])
        clarification = run_spec_refinement(spec, brief, question_budget=3)
        assert len(clarification.blocking_questions) <= 3

    def test_autonomous_mode_uses_spec_assumptions(self):
        """Autonomous mode populates assumptions from spec.assumptions."""
        spec = _make_spec(assumptions=["Assume Python 3.11"])
        brief = _make_brief()
        clarification = run_spec_refinement(spec, brief, question_budget=0)
        assert "Assume Python 3.11" in clarification.assumptions

    def test_autonomous_mode_includes_brief_unknowns_as_assumptions(self):
        """Autonomous mode includes brief.unknowns as assumptions."""
        spec = _make_spec()
        brief = _make_brief(unknowns=["Unknown dependency"])
        clarification = run_spec_refinement(spec, brief, question_budget=0)
        # unknowns from brief should appear in assumptions
        assert any("Unknown dependency" in a for a in clarification.assumptions)

    def test_hard_max_enforced_even_with_large_budget(self):
        """Question budget capped at 5 (hard max) even if question_budget > 5."""
        spec = _make_spec(
            requirements=["r1", "r2", "r3", "r4", "r5", "r6"],
            acceptance_criteria=["a1"],
        )
        brief = _make_brief(
            unknowns=["u1", "u2", "u3", "u4", "u5", "u6"]
        )
        clarification = run_spec_refinement(spec, brief, question_budget=10)
        assert len(clarification.blocking_questions) <= 5


# ---------------------------------------------------------------------------
# Task 4: should_trigger_architecture_council
# ---------------------------------------------------------------------------


class TestArchCouncilTrigger:
    def test_triggers_for_cross_module_target_files(self):
        """should_trigger returns True when target_files span 2+ top-level directories."""
        spec = _make_spec(target_files=["backend/api.py", "frontend/app.ts"])
        brief = _make_brief()
        assert should_trigger_architecture_council(spec, brief) is True

    def test_triggers_for_auth_keyword_in_requirements(self):
        """should_trigger returns True when requirements mention 'auth'."""
        spec = _make_spec(requirements=["Add auth to the API"])
        brief = _make_brief()
        assert should_trigger_architecture_council(spec, brief) is True

    def test_triggers_for_migration_keyword_in_requirements(self):
        """should_trigger returns True when requirements mention 'migration'."""
        spec = _make_spec(requirements=["Run database migration for users table"])
        brief = _make_brief()
        assert should_trigger_architecture_council(spec, brief) is True

    def test_triggers_for_security_keyword_in_requirements(self):
        """should_trigger returns True when requirements mention 'security'."""
        spec = _make_spec(requirements=["Fix security vulnerability in session handler"])
        brief = _make_brief()
        assert should_trigger_architecture_council(spec, brief) is True

    def test_does_not_trigger_for_simple_single_file_change(self):
        """should_trigger returns False for simple single-file change."""
        spec = _make_spec(
            requirements=["Add a helper function"],
            acceptance_criteria=["Function returns correct value"],
            target_files=["utils/helpers.py"],
        )
        brief = _make_brief(confidence="high")
        assert should_trigger_architecture_council(spec, brief) is False

    def test_triggers_for_architecture_in_context(self):
        """should_trigger returns True when spec.context mentions 'architecture'."""
        spec = _make_spec(
            context="Need to rethink the architecture for the data layer"
        )
        brief = _make_brief()
        assert should_trigger_architecture_council(spec, brief) is True

    def test_triggers_for_low_confidence_many_target_files(self):
        """should_trigger returns True for low confidence + >3 target files."""
        spec = _make_spec(
            target_files=["a.py", "b.py", "c.py", "d.py"],
        )
        brief = _make_brief(confidence="low")
        assert should_trigger_architecture_council(spec, brief) is True

    def test_run_arch_council_if_needed_returns_empty_when_no_trigger(self):
        """run_arch_council_if_needed returns [] when no trigger fires."""
        spec = _make_spec(target_files=["utils/helpers.py"])
        brief = _make_brief(confidence="high")
        notes = run_arch_council_if_needed(spec, brief)
        assert notes == []

    def test_run_arch_council_if_needed_returns_note_when_triggered(self):
        """run_arch_council_if_needed returns a note when triggered."""
        spec = _make_spec(requirements=["Implement auth system"])
        brief = _make_brief()
        notes = run_arch_council_if_needed(spec, brief)
        assert len(notes) == 1
        assert "Architecture council recommended" in notes[0]


# ---------------------------------------------------------------------------
# Task 5: check_spec_readiness
# ---------------------------------------------------------------------------


class TestReadinessCheck:
    def test_raises_when_requirements_empty(self):
        """check_spec_readiness raises ValueError when spec.requirements is empty."""
        # SpecArtifact itself validates requirements non-empty, so mock via brief
        # We need a spec with empty requirements — but SpecArtifact won't allow it.
        # Instead, test check_spec_readiness directly with a mocked-out spec.
        # Use model_construct to bypass validator for the test.
        spec = SpecArtifact.model_construct(
            spec_id="test-spec",
            title="Test",
            objective="Test",
            requirements=[],
            acceptance_criteria=["ac-1"],
            constraints=[],
            non_goals=[],
            context=None,
            target_files=[],
            assumptions=[],
            verification_hints=["pytest"],
        )
        brief = _make_brief(test_commands=["python3 -m pytest"])
        clarification = ClarificationPlan()
        with pytest.raises(ValueError, match="requirements must be non-empty"):
            check_spec_readiness(spec, brief, clarification)

    def test_raises_when_acceptance_criteria_empty(self):
        """check_spec_readiness raises ValueError when spec.acceptance_criteria is empty."""
        spec = SpecArtifact.model_construct(
            spec_id="test-spec",
            title="Test",
            objective="Test",
            requirements=["req-1"],
            acceptance_criteria=[],
            constraints=[],
            non_goals=[],
            context=None,
            target_files=[],
            assumptions=[],
            verification_hints=[],
        )
        brief = _make_brief(test_commands=["python3 -m pytest"])
        clarification = ClarificationPlan()
        with pytest.raises(ValueError, match="acceptance_criteria must be non-empty"):
            check_spec_readiness(spec, brief, clarification)

    def test_raises_when_no_verification_feasibility(self):
        """check_spec_readiness raises ValueError when no test_commands and no verification_hints."""
        spec = _make_spec(verification_hints=[])
        brief = _make_brief(test_commands=[])
        clarification = ClarificationPlan()
        with pytest.raises(ValueError, match="no verification feasibility"):
            check_spec_readiness(spec, brief, clarification)

    def test_succeeds_for_well_formed_spec(self):
        """check_spec_readiness succeeds for well-formed spec."""
        spec = _make_spec(verification_hints=["Run pytest"])
        brief = _make_brief(test_commands=["python3 -m pytest"])
        clarification = ClarificationPlan()
        # Should not raise
        result = check_spec_readiness(spec, brief, clarification)
        assert result is None


# ---------------------------------------------------------------------------
# Task 6: run_spec_prep — top-level stage runner
# ---------------------------------------------------------------------------


class TestRunSpecPrep:
    def test_returns_spec_prep_artifact(self, tmp_path):
        """run_spec_prep returns a SpecPrepArtifact."""
        run = _make_run()
        spec = _make_spec(verification_hints=["Run pytest"])
        registry = {"spec": spec}
        artifact = run_spec_prep(run, registry, None)
        assert isinstance(artifact, SpecPrepArtifact)

    def test_prep_id_has_prep_prefix(self, tmp_path):
        """run_spec_prep result prep_id starts with 'prep-'."""
        run = _make_run()
        spec = _make_spec(verification_hints=["Run pytest"])
        registry = {"spec": spec}
        artifact = run_spec_prep(run, registry, None)
        assert artifact.prep_id.startswith("prep-")

    def test_binding_decisions_is_list_of_str(self):
        """run_spec_prep result binding_decisions is list[str] (PREP-05)."""
        run = _make_run()
        spec = _make_spec(verification_hints=["Run pytest"])
        registry = {"spec": spec}
        artifact = run_spec_prep(run, registry, None)
        assert isinstance(artifact.binding_decisions, list)
        assert all(isinstance(d, str) for d in artifact.binding_decisions)

    def test_advisory_context_is_list_of_str(self):
        """run_spec_prep result advisory_context is list[str] (PREP-05)."""
        run = _make_run()
        spec = _make_spec(verification_hints=["Run pytest"])
        registry = {"spec": spec}
        artifact = run_spec_prep(run, registry, None)
        assert isinstance(artifact.advisory_context, list)
        assert all(isinstance(s, str) for s in artifact.advisory_context)

    def test_matches_stage_runner_signature(self):
        """run_spec_prep matches StageRunner signature (run, registry, guidance)."""
        from agentcouncil.autopilot.orchestrator import StageRunner
        import inspect
        sig = inspect.signature(run_spec_prep)
        params = list(sig.parameters.keys())
        # Must accept (run, registry, guidance)
        assert "run" in params
        assert "registry" in params
        assert "guidance" in params

    def test_works_without_spec_in_registry(self):
        """run_spec_prep constructs a minimal spec when registry has no 'spec' key."""
        run = _make_run(spec_id="my-feature")
        registry: dict = {}
        # Should not raise — minimal spec is constructed
        artifact = run_spec_prep(run, registry, None)
        assert isinstance(artifact, SpecPrepArtifact)
        assert artifact.finalized_spec.spec_id == "my-feature"

    def test_research_brief_is_populated(self):
        """run_spec_prep result has populated CodebaseResearchBrief in research field."""
        run = _make_run()
        spec = _make_spec(verification_hints=["Run pytest"])
        registry = {"spec": spec}
        artifact = run_spec_prep(run, registry, None)
        assert isinstance(artifact.research, CodebaseResearchBrief)
        assert artifact.research.summary

    def test_clarification_is_populated(self):
        """run_spec_prep result has ClarificationPlan in clarification field."""
        run = _make_run()
        spec = _make_spec(verification_hints=["Run pytest"])
        registry = {"spec": spec}
        artifact = run_spec_prep(run, registry, None)
        assert isinstance(artifact.clarification, ClarificationPlan)


# ---------------------------------------------------------------------------
# Acceptance-criteria-compatible standalone test names
# ---------------------------------------------------------------------------


def test_codebase_research_returns_brief(tmp_path):
    """Standalone: run_codebase_research returns CodebaseResearchBrief."""
    spec = _make_spec()
    brief = run_codebase_research(spec, project_root=tmp_path)
    assert isinstance(brief, CodebaseResearchBrief)
    assert brief.summary


def test_clarification_budget_hard_max():
    """Standalone: ClarificationPlan with > 5 questions raises ValidationError."""
    with pytest.raises(ValidationError):
        ClarificationPlan(blocking_questions=["q1", "q2", "q3", "q4", "q5", "q6"])


def test_arch_council_trigger_cross_module():
    """Standalone: should_trigger_architecture_council for cross-module files."""
    spec = _make_spec(target_files=["backend/api.py", "frontend/app.ts"])
    brief = _make_brief()
    assert should_trigger_architecture_council(spec, brief) is True


def test_readiness_check_success():
    """Standalone: check_spec_readiness succeeds for well-formed spec."""
    spec = _make_spec(verification_hints=["Run pytest"])
    brief = _make_brief(test_commands=["python3 -m pytest"])
    clarification = ClarificationPlan()
    assert check_spec_readiness(spec, brief, clarification) is None
