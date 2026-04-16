"""agentcouncil.autopilot.build -- build stage runner.

Implements the build stage: executes each task from PlanArtifact in order,
running tests, making focused commits, and recording per-task evidence into
a BuildArtifact.

Follows the workflow recipe in workflows/build/workflow.md:
- Increment cycle: Implement -> Test -> Verify -> Commit -> Record Evidence
- One task at a time (Rule 0)
- The plan is the contract (Rule 1)
- Tests travel with the code (Rule 2)
- Never commit broken tests (Rule 3)
- Evidence is not optional (Rule 4)
- Commit SHAs are audit trail (Rule 5)
"""
from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from agentcouncil.autopilot.artifacts import (
    BuildArtifact,
    BuildEvidence,
    PlanArtifact,
    SpecPrepArtifact,
)
from agentcouncil.autopilot.run import AutopilotRun

__all__ = ["run_build"]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str], cwd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a command and return (exit_code, stdout_tail, stderr_tail).

    Uses shell=False for security (FM-05).
    """
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout_tail = result.stdout[-2000:] if result.stdout else ""
        stderr_tail = result.stderr[-2000:] if result.stderr else ""
        return result.returncode, stdout_tail, stderr_tail
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"


def _git_diff_files(cwd: str) -> list[str]:
    """Return list of files with uncommitted changes (staged + unstaged)."""
    exit_code, stdout, _ = _run_cmd(
        ["git", "diff", "--name-only", "HEAD"], cwd, timeout=10,
    )
    if exit_code != 0:
        # Fallback: try without HEAD (initial repo)
        exit_code, stdout, _ = _run_cmd(
            ["git", "diff", "--name-only"], cwd, timeout=10,
        )

    # Also include untracked files
    exit_code2, stdout2, _ = _run_cmd(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd, timeout=10,
    )

    files = [f.strip() for f in stdout.splitlines() if f.strip()]
    if exit_code2 == 0:
        files.extend(f.strip() for f in stdout2.splitlines() if f.strip())
    return files


def _git_staged_files(cwd: str) -> list[str]:
    """Return list of staged files."""
    exit_code, stdout, _ = _run_cmd(
        ["git", "diff", "--cached", "--name-only"], cwd, timeout=10,
    )
    return [f.strip() for f in stdout.splitlines() if f.strip()]


def _git_commit(message: str, cwd: str) -> Optional[str]:
    """Stage all changes and commit. Returns SHA or None on failure."""
    # Stage all changes
    exit_code, _, stderr = _run_cmd(["git", "add", "-A"], cwd, timeout=10)
    if exit_code != 0:
        return None

    # Check if there's anything to commit
    staged = _git_staged_files(cwd)
    if not staged:
        return None

    # Commit
    exit_code, stdout, stderr = _run_cmd(
        ["git", "commit", "-m", message], cwd, timeout=30,
    )
    if exit_code != 0:
        return None

    # Get the SHA
    exit_code, stdout, _ = _run_cmd(
        ["git", "rev-parse", "HEAD"], cwd, timeout=10,
    )
    return stdout.strip() if exit_code == 0 else None


def _run_tests(test_commands: list[str], cwd: str, timeout: int = 60) -> tuple[bool, str]:
    """Run test commands and return (all_passing, summary).

    Returns (True, summary) if all commands exit 0, (False, summary) otherwise.
    """
    if not test_commands:
        return True, "No test commands configured; skipping tests."

    summaries: list[str] = []
    all_passing = True

    for cmd_str in test_commands:
        import shlex
        cmd = shlex.split(cmd_str)
        exit_code, stdout, stderr = _run_cmd(cmd, cwd, timeout=timeout)

        if exit_code == 0:
            summaries.append(f"'{cmd_str}' passed")
        else:
            all_passing = False
            error_tail = stderr[-200:] if stderr else stdout[-200:] if stdout else "no output"
            summaries.append(f"'{cmd_str}' failed (exit {exit_code}): {error_tail}")

    return all_passing, "; ".join(summaries)


# ---------------------------------------------------------------------------
# Per-task execution
# ---------------------------------------------------------------------------


def _execute_task(
    task_id: str,
    task_title: str,
    task_description: str,
    task_target_files: list[str],
    task_criteria: list[str],
    test_commands: list[str],
    cwd: str,
) -> tuple[BuildEvidence, Optional[str], bool]:
    """Execute a single build task and record evidence.

    This runner verifies existing work rather than generating code — the
    autopilot pipeline assumes Claude (the host agent) implements the code
    before or during the build stage. The runner captures evidence of what
    changed, runs tests, and commits.

    Returns (evidence, commit_sha, tests_passing).
    """
    # Detect which files actually changed for this task
    changed_files = _git_diff_files(cwd)

    # Filter to task's target files if possible, otherwise use all changes
    if task_target_files:
        relevant_changes = [
            f for f in changed_files
            if any(f.endswith(tf) or tf in f for tf in task_target_files)
        ]
        # Include all changes if no target match (task may have created new files)
        if not relevant_changes:
            relevant_changes = changed_files
    else:
        relevant_changes = changed_files

    # Run tests only if there are actual file changes to verify
    # (avoids running the full test suite when no code was modified)
    if relevant_changes:
        tests_passing, test_summary = _run_tests(test_commands, cwd)
    else:
        tests_passing = True
        test_summary = "No files changed; test run skipped."

    # Build verification notes
    verification_parts: list[str] = []
    for criterion in task_criteria:
        verification_parts.append(f"Criterion: {criterion}")
    if relevant_changes:
        verification_parts.append(f"Files changed: {', '.join(relevant_changes[:20])}")
    verification_parts.append(f"Tests: {test_summary}")
    verification_notes = ". ".join(verification_parts)

    # Commit if there are changes (even if tests fail — Rule 3 says don't
    # commit broken tests, but we record evidence regardless)
    commit_sha: Optional[str] = None
    if relevant_changes and tests_passing:
        commit_msg = f"feat(autopilot): {task_title}"
        commit_sha = _git_commit(commit_msg, cwd)

    evidence = BuildEvidence(
        task_id=task_id,
        files_changed=relevant_changes,
        test_results=test_summary,
        verification_notes=verification_notes,
    )

    return evidence, commit_sha, tests_passing


# ---------------------------------------------------------------------------
# Top-level stage runner
# ---------------------------------------------------------------------------


def run_build(
    run: AutopilotRun,
    registry: dict[str, Any],
    guidance: Optional[str] = None,
) -> BuildArtifact:
    """Build stage runner — produces BuildArtifact from PlanArtifact.

    Matches StageRunner callable signature: (run, registry, guidance) -> artifact.

    Executes each task in PlanArtifact.execution_order:
    1. Detect file changes for the task
    2. Run test commands
    3. Record evidence
    4. Commit if tests pass

    When revision guidance is provided (from a verify->build retry or gate
    revise), it is noted in the first task's evidence.
    """
    # Extract PlanArtifact from registry
    plan = registry.get("plan")
    if not isinstance(plan, PlanArtifact):
        if isinstance(plan, dict):
            plan = PlanArtifact(**plan)
        else:
            raise ValueError(
                "Build stage requires PlanArtifact in registry['plan']. "
                f"Got: {type(plan).__name__}"
            )

    # Extract test commands from spec_prep research
    test_commands: list[str] = []
    prep = registry.get("spec_prep")
    if isinstance(prep, SpecPrepArtifact):
        test_commands = list(prep.research.test_commands)
    elif isinstance(prep, dict):
        research = prep.get("research", {})
        test_commands = research.get("test_commands", [])

    cwd = str(Path.cwd())

    # Build task lookup
    task_map = {t.task_id: t for t in plan.tasks}

    # Execute tasks in order
    all_evidence: list[BuildEvidence] = []
    all_commit_shas: list[str] = []
    all_files_changed: set[str] = set()
    all_tests_passing = True

    for i, task_id in enumerate(plan.execution_order):
        task = task_map.get(task_id)
        if task is None:
            # Skip unknown task IDs (shouldn't happen with valid PlanArtifact)
            continue

        evidence, commit_sha, tests_ok = _execute_task(
            task_id=task.task_id,
            task_title=task.title,
            task_description=task.description,
            task_target_files=task.target_files,
            task_criteria=task.acceptance_criteria,
            test_commands=test_commands,
            cwd=cwd,
        )

        # Annotate first task with revision guidance if present
        if i == 0 and guidance:
            evidence.verification_notes += f". REVISION GUIDANCE: {guidance}"

        all_evidence.append(evidence)
        if commit_sha:
            all_commit_shas.append(commit_sha)
        all_files_changed.update(evidence.files_changed)
        if not tests_ok:
            all_tests_passing = False

    # Ensure at least one evidence entry (BuildArtifact requires non-empty)
    if not all_evidence:
        all_evidence.append(BuildEvidence(
            task_id="no-tasks",
            files_changed=[],
            verification_notes="No tasks executed.",
        ))

    build_id = f"build-{uuid.uuid4().hex[:8]}"

    return BuildArtifact(
        build_id=build_id,
        plan_id=plan.plan_id,
        spec_id=plan.spec_id,
        evidence=all_evidence,
        all_tests_passing=all_tests_passing,
        files_changed=sorted(all_files_changed),
        commit_shas=all_commit_shas,
    )
