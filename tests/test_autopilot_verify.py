"""Tests for agentcouncil.autopilot.verify and agentcouncil.autopilot.ship."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentcouncil.autopilot.artifacts import (
    AcceptanceProbe,
    BuildArtifact,
    BuildEvidence,
    CommandEvidence,
    CriterionVerification,
    PlanArtifact,
    PlanTask,
    VerificationEnvironment,
    VerifyArtifact,
    ShipArtifact,
)
from agentcouncil.autopilot.run import AutopilotRun

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run() -> AutopilotRun:
    import time as _time
    now = _time.time()
    return AutopilotRun(
        run_id="test-run-1",
        spec_id="spec-1",
        status="running",
        current_stage="verify",
        tier=2,
        stages=[],
        started_at=now,
        updated_at=now,
    )


def _make_probe(
    probe_id: str = "probe-1",
    criterion_id: str = "ac-0",
    criterion_text: str = "The system does X",
    verification_level: str = "unit",
    command_hint: str | None = None,
) -> AcceptanceProbe:
    return AcceptanceProbe(
        probe_id=probe_id,
        criterion_id=criterion_id,
        criterion_text=criterion_text,
        verification_level=verification_level,
        target_behavior="Does X correctly",
        command_hint=command_hint,
        expected_observation="X happens",
        mock_policy="allowed",
    )


def _make_env(
    test_commands: list[str] | None = None,
    playwright_available: bool = False,
) -> VerificationEnvironment:
    return VerificationEnvironment(
        project_types=["python"],
        test_commands=test_commands or [],
        playwright_available=playwright_available,
    )


def _make_plan(probes: list[AcceptanceProbe] | None = None) -> PlanArtifact:
    task = PlanTask(
        task_id="t-1",
        title="Test task",
        description="Do something",
        acceptance_criteria=["criterion 1"],
    )
    return PlanArtifact(
        plan_id="plan-1",
        spec_id="spec-1",
        tasks=[task],
        execution_order=["t-1"],
        verification_strategy="unit tests",
        acceptance_probes=probes or [],
    )


def _make_build() -> BuildArtifact:
    return BuildArtifact(
        build_id="build-1",
        plan_id="plan-1",
        spec_id="spec-1",
        evidence=[
            BuildEvidence(
                task_id="t-1",
                files_changed=["src/main.py"],
                verification_notes="built ok",
            )
        ],
        all_tests_passing=True,
        files_changed=["src/main.py"],
        commit_shas=["abc1234"],
    )


# ---------------------------------------------------------------------------
# Task 1: verify.py tests
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for run_command() — real subprocess execution."""

    def test_real_command_execution_echo(self) -> None:
        """run_command('echo hello') returns exit_code=0 and stdout_tail contains 'hello'."""
        from agentcouncil.autopilot.verify import run_command

        evidence = run_command("echo hello", cwd="/tmp")
        assert evidence.exit_code == 0
        assert "hello" in evidence.stdout_tail
        assert evidence.command == "echo hello"
        assert evidence.cwd == "/tmp"
        assert evidence.duration_seconds >= 0

    def test_run_command_failing(self) -> None:
        """run_command('false') returns non-zero exit code."""
        from agentcouncil.autopilot.verify import run_command

        evidence = run_command("false", cwd="/tmp")
        assert evidence.exit_code != 0

    def test_run_command_captures_stdout_tail(self) -> None:
        """stdout_tail is truncated to last 2000 chars."""
        from agentcouncil.autopilot.verify import run_command

        evidence = run_command("echo hello world", cwd="/tmp")
        assert isinstance(evidence.stdout_tail, str)
        assert len(evidence.stdout_tail) <= 2000

    def test_run_command_returns_command_evidence(self) -> None:
        """run_command returns a CommandEvidence instance."""
        from agentcouncil.autopilot.verify import run_command

        evidence = run_command("echo test", cwd="/tmp")
        assert isinstance(evidence, CommandEvidence)


class TestDiscoverVerificationEnvironment:
    """Tests for discover_verification_environment()."""

    def test_playwright_not_available(self) -> None:
        """playwright_available=False when playwright not installed."""
        from agentcouncil.autopilot.verify import discover_verification_environment

        run = _make_run()
        with patch("importlib.util.find_spec", return_value=None):
            env = discover_verification_environment(run)
        assert env.playwright_available is False

    def test_playwright_available(self) -> None:
        """playwright_available=True when playwright is installed."""
        from agentcouncil.autopilot.verify import discover_verification_environment

        run = _make_run()
        mock_spec = MagicMock()
        with patch("importlib.util.find_spec", return_value=mock_spec):
            env = discover_verification_environment(run)
        assert env.playwright_available is True

    def test_returns_verification_environment(self) -> None:
        """Returns a VerificationEnvironment instance."""
        from agentcouncil.autopilot.verify import discover_verification_environment

        run = _make_run()
        with patch("importlib.util.find_spec", return_value=None):
            env = discover_verification_environment(run)
        assert isinstance(env, VerificationEnvironment)


class TestExecuteCriterion:
    """Tests for execute_criterion() — five-level dispatch."""

    def test_execute_criterion_with_command_hint(self) -> None:
        """execute_criterion runs probe.command_hint if provided."""
        from agentcouncil.autopilot.verify import execute_criterion

        probe = _make_probe(verification_level="unit", command_hint="echo test_hint")
        env = _make_env()
        result = execute_criterion(probe, env, cwd="/tmp")
        assert isinstance(result, CriterionVerification)
        assert result.criterion_id == "ac-0"
        assert len(result.commands) > 0
        assert result.commands[0].command == "echo test_hint"

    def test_execute_criterion_static_level(self) -> None:
        """Static level dispatches differently from unit level."""
        from agentcouncil.autopilot.verify import execute_criterion

        probe_static = _make_probe(
            verification_level="static", command_hint="echo static_check"
        )
        probe_unit = _make_probe(
            verification_level="unit", command_hint="echo unit_check"
        )
        env = _make_env()
        result_static = execute_criterion(probe_static, env, cwd="/tmp")
        result_unit = execute_criterion(probe_unit, env, cwd="/tmp")

        assert result_static.verification_level == "static"
        assert result_unit.verification_level == "unit"

    def test_execute_criterion_e2e_without_playwright_skipped(self) -> None:
        """e2e probe skipped with skip_reason when playwright not available."""
        from agentcouncil.autopilot.verify import execute_criterion

        probe = _make_probe(verification_level="e2e")
        env = _make_env(playwright_available=False)
        result = execute_criterion(probe, env, cwd="/tmp")
        assert result.status == "skipped"
        assert result.skip_reason is not None
        assert "playwright" in result.skip_reason.lower() or "Playwright" in result.skip_reason

    def test_execute_criterion_returns_criterion_verification(self) -> None:
        """execute_criterion always returns a CriterionVerification."""
        from agentcouncil.autopilot.verify import execute_criterion

        probe = _make_probe(verification_level="unit", command_hint="echo ok")
        env = _make_env()
        result = execute_criterion(probe, env, cwd="/tmp")
        assert isinstance(result, CriterionVerification)
        assert result.criterion_text == probe.criterion_text
        assert result.mock_policy == probe.mock_policy

    def test_execute_criterion_failed_has_diagnosis(self) -> None:
        """Failed criterion gets failure_diagnosis and revision_guidance."""
        from agentcouncil.autopilot.verify import execute_criterion

        probe = _make_probe(verification_level="unit", command_hint="false")
        env = _make_env()
        result = execute_criterion(probe, env, cwd="/tmp")
        assert result.status == "failed"
        assert result.failure_diagnosis is not None
        assert result.revision_guidance is not None


class TestGenerateProbes:
    """Tests for generate_probes() — stub generation when test infra missing."""

    def test_probe_generation_when_no_test_commands(self) -> None:
        """generate_probes returns stubs when test_commands is empty."""
        from agentcouncil.autopilot.verify import generate_probes

        probes = [_make_probe(probe_id="p-1"), _make_probe(probe_id="p-2", criterion_id="ac-1")]
        env = _make_env(test_commands=[])
        generated = generate_probes(probes, env)
        assert len(generated) > 0

    def test_generate_probes_returns_strings(self) -> None:
        """Each generated probe is a string."""
        from agentcouncil.autopilot.verify import generate_probes

        probes = [_make_probe()]
        env = _make_env(test_commands=[])
        generated = generate_probes(probes, env)
        assert all(isinstance(g, str) for g in generated)

    def test_generate_probes_returns_empty_when_test_commands_exist(self) -> None:
        """generate_probes returns empty list when test infrastructure exists."""
        from agentcouncil.autopilot.verify import generate_probes

        probes = [_make_probe()]
        env = _make_env(test_commands=["python3 -m pytest"])
        generated = generate_probes(probes, env)
        assert generated == []


class TestRunVerify:
    """Tests for run_verify() — top-level stage runner."""

    def test_run_verify_produces_one_verdict_per_probe(self) -> None:
        """run_verify returns one CriterionVerification per AcceptanceProbe."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        probes = [
            _make_probe(probe_id="p-1", criterion_id="ac-0", command_hint="echo p1"),
            _make_probe(probe_id="p-2", criterion_id="ac-1", command_hint="echo p2"),
        ]
        plan = _make_plan(probes=probes)
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        artifact = run_verify(run, registry, None)
        assert len(artifact.criteria_verdicts) == 2

    def test_run_verify_all_passing_returns_passed(self) -> None:
        """run_verify returns overall_status='passed' when all probes pass."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        probes = [
            _make_probe(probe_id="p-1", criterion_id="ac-0", command_hint="echo ok"),
        ]
        plan = _make_plan(probes=probes)
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        artifact = run_verify(run, registry, None)
        assert artifact.overall_status == "passed"

    def test_run_verify_failing_probe_returns_failed(self) -> None:
        """run_verify returns overall_status='failed' with retry recommendation when probe fails."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        probes = [
            _make_probe(probe_id="p-1", criterion_id="ac-0", command_hint="false"),
        ]
        plan = _make_plan(probes=probes)
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        artifact = run_verify(run, registry, None)
        assert artifact.overall_status == "failed"
        assert artifact.retry_recommendation == "retry_build"
        assert artifact.revision_guidance is not None

    def test_run_verify_matches_stage_runner_signature(self) -> None:
        """run_verify is callable with (run, registry, guidance) signature."""
        from agentcouncil.autopilot.verify import run_verify
        import inspect

        sig = inspect.signature(run_verify)
        params = list(sig.parameters.keys())
        assert "run" in params
        assert "registry" in params
        assert "guidance" in params

    def test_run_verify_returns_verify_artifact(self) -> None:
        """run_verify returns a VerifyArtifact instance."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        plan = _make_plan(probes=[])
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        artifact = run_verify(run, registry, None)
        assert isinstance(artifact, VerifyArtifact)

    def test_per_criterion_evidence(self) -> None:
        """Each verdict in criteria_verdicts contains the probe's criterion info."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        probes = [
            _make_probe(probe_id="p-1", criterion_id="ac-0", criterion_text="Feature X works", command_hint="echo x"),
        ]
        plan = _make_plan(probes=probes)
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        artifact = run_verify(run, registry, None)
        assert artifact.criteria_verdicts[0].criterion_id == "ac-0"
        assert artifact.criteria_verdicts[0].criterion_text == "Feature X works"

    def test_verification_levels_respected(self) -> None:
        """Each verdict preserves the probe's verification_level."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        probes = [
            _make_probe(probe_id="p-1", criterion_id="ac-0", verification_level="static", command_hint="echo s"),
            _make_probe(probe_id="p-2", criterion_id="ac-1", verification_level="unit", command_hint="echo u"),
        ]
        plan = _make_plan(probes=probes)
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        artifact = run_verify(run, registry, None)
        levels = {v.criterion_id: v.verification_level for v in artifact.criteria_verdicts}
        assert levels["ac-0"] == "static"
        assert levels["ac-1"] == "unit"

    def test_playwright_skipped(self) -> None:
        """E2e probes are skipped when playwright is not available."""
        from agentcouncil.autopilot.verify import run_verify

        run = _make_run()
        probes = [
            _make_probe(probe_id="p-1", criterion_id="ac-0", verification_level="e2e"),
        ]
        plan = _make_plan(probes=probes)
        build = _make_build()
        registry: dict[str, Any] = {"plan": plan, "build": build}
        # Patch playwright to be unavailable
        with patch("importlib.util.find_spec", return_value=None):
            artifact = run_verify(run, registry, None)
        assert artifact.criteria_verdicts[0].status == "skipped"
        assert artifact.criteria_verdicts[0].skip_reason is not None


# ---------------------------------------------------------------------------
# Task 2: ship.py tests
# ---------------------------------------------------------------------------


class TestRunShip:
    """Tests for run_ship() — ship stage runner."""

    def _make_passing_verify_artifact(self) -> VerifyArtifact:
        verdict = CriterionVerification(
            criterion_id="ac-0",
            criterion_text="Works",
            status="passed",
            verification_level="unit",
            mock_policy="allowed",
            evidence_summary="echo ok exit 0",
        )
        return VerifyArtifact(
            verify_id="verify-1",
            build_id="build-1",
            plan_id="plan-1",
            spec_id="spec-1",
            test_environment=VerificationEnvironment(),
            criteria_verdicts=[verdict],
            overall_status="passed",
            retry_recommendation="none",
        )

    def _make_failing_verify_artifact(self) -> VerifyArtifact:
        verdict = CriterionVerification(
            criterion_id="ac-0",
            criterion_text="Feature X works",
            status="failed",
            verification_level="unit",
            mock_policy="allowed",
            evidence_summary="exit 1",
            failure_diagnosis="command exited non-zero",
            revision_guidance="Fix the implementation",
        )
        return VerifyArtifact(
            verify_id="verify-2",
            build_id="build-1",
            plan_id="plan-1",
            spec_id="spec-1",
            test_environment=VerificationEnvironment(),
            criteria_verdicts=[verdict],
            overall_status="failed",
            retry_recommendation="retry_build",
            revision_guidance="Fix the implementation",
        )

    def test_ship_artifact_fields_present(self) -> None:
        """run_ship returns ShipArtifact with ship_id, branch_name, head_sha, etc."""
        from agentcouncil.autopilot.ship import run_ship

        run = _make_run()
        verify_art = self._make_passing_verify_artifact()
        build = _make_build()
        plan = _make_plan()
        registry: dict[str, Any] = {"verify": verify_art, "build": build, "plan": plan}

        with patch("agentcouncil.autopilot.ship._get_git_info", return_value=("main", "abc1234")):
            with patch("agentcouncil.autopilot.ship._check_worktree_clean", return_value=True):
                artifact = run_ship(run, registry, None)

        assert isinstance(artifact, ShipArtifact)
        assert artifact.ship_id.startswith("ship-")
        assert artifact.branch_name == "main"
        assert artifact.head_sha == "abc1234"
        assert artifact.release_notes != ""
        assert artifact.rollback_plan != ""

    def test_ship_with_passed_verify_recommends_ship(self) -> None:
        """run_ship with passing VerifyArtifact sets recommended_action='ship'."""
        from agentcouncil.autopilot.ship import run_ship

        run = _make_run()
        verify_art = self._make_passing_verify_artifact()
        build = _make_build()
        plan = _make_plan()
        registry: dict[str, Any] = {"verify": verify_art, "build": build, "plan": plan}

        with patch("agentcouncil.autopilot.ship._get_git_info", return_value=("main", "abc1234")):
            with patch("agentcouncil.autopilot.ship._check_worktree_clean", return_value=True):
                artifact = run_ship(run, registry, None)

        assert artifact.recommended_action == "ship"
        assert artifact.tests_passing is True
        assert artifact.acceptance_criteria_met is True

    def test_ship_with_failed_verify_recommends_hold(self) -> None:
        """run_ship with failing VerifyArtifact sets recommended_action='hold' and remaining_risks."""
        from agentcouncil.autopilot.ship import run_ship

        run = _make_run()
        verify_art = self._make_failing_verify_artifact()
        build = _make_build()
        plan = _make_plan()
        registry: dict[str, Any] = {"verify": verify_art, "build": build, "plan": plan}

        with patch("agentcouncil.autopilot.ship._get_git_info", return_value=("main", "abc1234")):
            with patch("agentcouncil.autopilot.ship._check_worktree_clean", return_value=True):
                artifact = run_ship(run, registry, None)

        assert artifact.recommended_action == "hold"
        assert artifact.tests_passing is False
        assert len(artifact.remaining_risks) > 0

    def test_ship_matches_stage_runner_signature(self) -> None:
        """run_ship is callable with (run, registry, guidance) signature."""
        from agentcouncil.autopilot.ship import run_ship
        import inspect

        sig = inspect.signature(run_ship)
        params = list(sig.parameters.keys())
        assert "run" in params
        assert "registry" in params
        assert "guidance" in params

    def test_ship_git_branch_and_sha_populated(self) -> None:
        """run_ship calls git helpers to get branch_name and head_sha."""
        from agentcouncil.autopilot.ship import run_ship

        run = _make_run()
        verify_art = self._make_passing_verify_artifact()
        build = _make_build()
        plan = _make_plan()
        registry: dict[str, Any] = {"verify": verify_art, "build": build, "plan": plan}

        with patch("agentcouncil.autopilot.ship._get_git_info", return_value=("feature-branch", "deadbeef")) as mock_git:
            with patch("agentcouncil.autopilot.ship._check_worktree_clean", return_value=True):
                artifact = run_ship(run, registry, None)

        mock_git.assert_called_once()
        assert artifact.branch_name == "feature-branch"
        assert artifact.head_sha == "deadbeef"

    def test_ship_release_notes_and_rollback_nonempty(self) -> None:
        """run_ship always populates release_notes and rollback_plan."""
        from agentcouncil.autopilot.ship import run_ship

        run = _make_run()
        verify_art = self._make_passing_verify_artifact()
        build = _make_build()
        plan = _make_plan()
        registry: dict[str, Any] = {"verify": verify_art, "build": build, "plan": plan}

        with patch("agentcouncil.autopilot.ship._get_git_info", return_value=("main", "sha123")):
            with patch("agentcouncil.autopilot.ship._check_worktree_clean", return_value=True):
                artifact = run_ship(run, registry, None)

        assert artifact.release_notes != ""
        assert artifact.rollback_plan != ""
        assert "sha123" in artifact.rollback_plan
