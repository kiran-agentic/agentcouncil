"""agentcouncil.autopilot.verify -- verify stage runner.

Implements VER-01 through VER-06: five-level verification, real command
execution, per-criterion evidence, probe generation, Playwright support.
"""
from __future__ import annotations

import importlib.util
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from agentcouncil.autopilot.artifacts import (
    AcceptanceProbe,
    BuildArtifact,
    CommandEvidence,
    CriterionVerification,
    PlanArtifact,
    ServiceEvidence,
    VerificationEnvironment,
    VerifyArtifact,
)
from agentcouncil.autopilot.run import AutopilotRun

__all__ = ["run_verify"]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def run_command(cmd: str, cwd: str, timeout: int = 60) -> CommandEvidence:
    """Execute a shell command and capture structured evidence (VER-02).

    Uses real subprocess execution — not mocked at this level.
    Captures stdout_tail and stderr_tail (last 2000 chars each).
    """
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start
        stdout_tail = result.stdout[-2000:] if result.stdout else ""
        stderr_tail = result.stderr[-2000:] if result.stderr else ""
        return CommandEvidence(
            command=cmd,
            cwd=cwd,
            exit_code=result.returncode,
            duration_seconds=duration,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        return CommandEvidence(
            command=cmd,
            cwd=cwd,
            exit_code=-1,
            duration_seconds=duration,
            stdout_tail="",
            stderr_tail=f"Command timed out after {timeout}s",
        )


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def discover_verification_environment(run: AutopilotRun) -> VerificationEnvironment:
    """Detect the runtime verification environment (VER-01).

    Checks project types, test commands, and Playwright availability.
    """
    cwd = Path.cwd()

    # Playwright availability check
    playwright_available = importlib.util.find_spec("playwright") is not None

    # Project type detection
    project_types: list[str] = []
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        project_types.append("python")
    if (cwd / "package.json").exists():
        project_types.append("node")
    if (cwd / "Cargo.toml").exists():
        project_types.append("rust")

    # Test command detection
    test_commands: list[str] = []
    if (cwd / "pyproject.toml").exists():
        try:
            content = (cwd / "pyproject.toml").read_text()
            if "[tool.pytest" in content or "pytest" in content:
                test_commands.append("python3 -m pytest")
        except OSError:
            pass
    if (cwd / "package.json").exists():
        try:
            import json
            pkg = json.loads((cwd / "package.json").read_text())
            if "scripts" in pkg and "test" in pkg["scripts"]:
                test_commands.append("npm test")
        except (OSError, ValueError):
            pass

    return VerificationEnvironment(
        project_types=project_types,
        test_commands=test_commands,
        playwright_available=playwright_available,
        confidence="medium",
    )


# ---------------------------------------------------------------------------
# Probe generation (VER-05)
# ---------------------------------------------------------------------------


def generate_probes(
    probes: list[AcceptanceProbe], env: VerificationEnvironment
) -> list[str]:
    """Generate minimal test stubs when no test infrastructure exists (VER-05).

    Returns list of generated test file content strings (not written to disk).
    Returns empty list if test_commands already exist.
    """
    if env.test_commands:
        return []

    generated: list[str] = []
    for probe in probes:
        stub = (
            f"# Auto-generated stub for criterion {probe.criterion_id}\n"
            f"# Criterion: {probe.criterion_text}\n"
            f"# Target behavior: {probe.target_behavior}\n"
            f"# Expected observation: {probe.expected_observation}\n"
            f"\n"
            f"def test_{probe.probe_id.replace('-', '_')}():\n"
            f'    """Verify: {probe.criterion_text}"""\n'
            f"    # TODO: implement verification for {probe.criterion_id}\n"
            f"    # Hint: {probe.command_hint or 'no command hint provided'}\n"
            f"    raise NotImplementedError('Stub test — implement real verification')\n"
        )
        generated.append(stub)

    return generated


# ---------------------------------------------------------------------------
# Per-criterion execution (VER-01, VER-03)
# ---------------------------------------------------------------------------


def execute_criterion(
    probe: AcceptanceProbe,
    env: VerificationEnvironment,
    cwd: str,
) -> CriterionVerification:
    """Execute a single acceptance probe and produce a CriterionVerification (VER-01, VER-03).

    Dispatches by verification_level:
    - static: static analysis or command_hint
    - unit: command_hint or first test_command
    - integration: command_hint priority, real subprocess, no mocks
    - smoke: command_hint or basic health check
    - e2e: Playwright if available, else skipped
    """
    level = probe.verification_level

    # E2E: Playwright gate (VER-06)
    if level == "e2e":
        if not env.playwright_available:
            return CriterionVerification(
                criterion_id=probe.criterion_id,
                criterion_text=probe.criterion_text,
                status="skipped",
                verification_level=level,
                mock_policy=probe.mock_policy,
                evidence_summary="E2E verification skipped: Playwright not available.",
                skip_reason="Playwright not available for e2e verification",
            )
        # Playwright available — attempt via command_hint or skip
        if probe.command_hint:
            evidence = run_command(probe.command_hint, cwd=cwd)
            return _build_verdict(probe, [evidence])
        else:
            return CriterionVerification(
                criterion_id=probe.criterion_id,
                criterion_text=probe.criterion_text,
                status="skipped",
                verification_level=level,
                mock_policy=probe.mock_policy,
                evidence_summary="E2E verification skipped: no Playwright test command configured.",
                skip_reason="No e2e test command configured",
            )

    # Determine command to run
    cmd: Optional[str] = None
    if probe.command_hint:
        cmd = probe.command_hint
    elif level in ("unit", "integration") and env.test_commands:
        cmd = env.test_commands[0]
    elif level == "smoke" and env.health_checks:
        cmd = env.health_checks[0]
    elif level == "static" and env.test_commands:
        cmd = env.test_commands[0]

    if cmd is None:
        # No command available — skip
        return CriterionVerification(
            criterion_id=probe.criterion_id,
            criterion_text=probe.criterion_text,
            status="skipped",
            verification_level=level,
            mock_policy=probe.mock_policy,
            evidence_summary=f"No command available for {level} verification.",
            skip_reason=f"No {level} verification command configured",
        )

    evidence = run_command(cmd, cwd=cwd)
    return _build_verdict(probe, [evidence])


def _build_verdict(
    probe: AcceptanceProbe,
    evidences: list[CommandEvidence],
) -> CriterionVerification:
    """Build a CriterionVerification from collected command evidence."""
    # Determine status from evidence
    status: str
    if not evidences:
        status = "skipped"
        skip_reason: Optional[str] = "No commands executed"
        failure_diagnosis: Optional[str] = None
        revision_guidance: Optional[str] = None
    else:
        last_exit = evidences[-1].exit_code
        if last_exit == 0:
            status = "passed"
            skip_reason = None
            failure_diagnosis = None
            revision_guidance = None
        else:
            status = "failed"
            skip_reason = None
            failure_diagnosis = (
                f"Command '{evidences[-1].command}' exited with code {last_exit}. "
                f"stderr: {evidences[-1].stderr_tail[:200]}"
            )
            revision_guidance = (
                f"Fix the implementation for criterion '{probe.criterion_id}': "
                f"{probe.criterion_text}. "
                f"Re-run: {evidences[-1].command}"
            )

    # Build evidence summary
    if evidences:
        cmd_summary = ", ".join(f"'{e.command}' (exit {e.exit_code})" for e in evidences)
        evidence_summary = f"Ran: {cmd_summary}. Result: {status}."
    else:
        evidence_summary = "No commands were executed."

    return CriterionVerification(
        criterion_id=probe.criterion_id,
        criterion_text=probe.criterion_text,
        status=status,
        verification_level=probe.verification_level,
        mock_policy=probe.mock_policy,
        evidence_summary=evidence_summary,
        commands=evidences,
        failure_diagnosis=failure_diagnosis,
        revision_guidance=revision_guidance,
        skip_reason=skip_reason,
    )


# ---------------------------------------------------------------------------
# Revision guidance builder
# ---------------------------------------------------------------------------


def _build_revision_guidance(verdicts: list[CriterionVerification]) -> str:
    """Collect guidance from all failed verdicts into a single string."""
    failed = [v for v in verdicts if v.status == "failed"]
    if not failed:
        return "No failed criteria."

    parts: list[str] = []
    for v in failed:
        diagnosis = v.failure_diagnosis or "Unknown failure"
        guidance = v.revision_guidance or "Review and fix the implementation"
        parts.append(
            f"[{v.criterion_id}] {v.criterion_text}\n"
            f"  Diagnosis: {diagnosis}\n"
            f"  Fix: {guidance}"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Top-level stage runner
# ---------------------------------------------------------------------------


def run_verify(
    run: AutopilotRun,
    registry: dict[str, Any],
    guidance: Optional[str] = None,
) -> VerifyArtifact:
    """Verify stage runner — produces VerifyArtifact with per-criterion evidence.

    Matches StageRunner callable signature: (run, registry, guidance) -> artifact.

    Implements VER-01 through VER-06.
    """
    # Extract artifacts from registry
    plan_art = registry.get("plan")
    if not isinstance(plan_art, PlanArtifact):
        # Construct minimal stub with empty probes
        plan_art = PlanArtifact(
            plan_id=run.spec_id or "plan-unknown",
            spec_id=run.spec_id or "spec-unknown",
            tasks=[],
            execution_order=[],
            verification_strategy="stub",
        ) if False else None  # type: ignore[assignment]
        # Fallback: no plan_art means empty probes
        acceptance_probes: list[AcceptanceProbe] = []
        plan_id = run.spec_id or "plan-unknown"
        spec_id = run.spec_id or "spec-unknown"
    else:
        acceptance_probes = plan_art.acceptance_probes
        plan_id = plan_art.plan_id
        spec_id = plan_art.spec_id

    build_art = registry.get("build")
    build_id = build_art.build_id if isinstance(build_art, BuildArtifact) else "build-unknown"

    # Discover environment
    env = discover_verification_environment(run)

    # Generate probes if no test infrastructure exists
    generated_tests: list[str] = []
    if not env.test_commands and acceptance_probes:
        generated_tests = generate_probes(acceptance_probes, env)

    # Execute each criterion
    cwd = str(Path.cwd())
    verdicts: list[CriterionVerification] = []
    for probe in acceptance_probes:
        verdict = execute_criterion(probe, env, cwd=cwd)
        verdicts.append(verdict)

    # Compute overall status
    failing_statuses = {"failed", "blocked"}
    if any(v.status in failing_statuses for v in verdicts):
        overall_status = "failed"
    else:
        overall_status = "passed"

    # Retry recommendation and revision guidance
    retry_recommendation: str
    revision_guidance: Optional[str]
    if overall_status == "failed":
        retry_recommendation = "retry_build"
        revision_guidance = _build_revision_guidance(verdicts)
    else:
        retry_recommendation = "none"
        revision_guidance = None

    return VerifyArtifact(
        verify_id=f"verify-{uuid.uuid4().hex[:8]}",
        build_id=build_id,
        plan_id=plan_id,
        spec_id=spec_id,
        test_environment=env,
        criteria_verdicts=verdicts,
        overall_status=overall_status,
        generated_tests=generated_tests,
        retry_recommendation=retry_recommendation,
        revision_guidance=revision_guidance,
    )
