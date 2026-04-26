"""agentcouncil.autopilot.ship -- ship stage runner.

Implements PERS-03: deterministic readiness packaging with branch/SHA,
verification status, release notes, and rollback plan.
"""
from __future__ import annotations

import subprocess
import uuid
from typing import Any, Optional

from agentcouncil.autopilot.artifacts import (
    BuildArtifact,
    CriterionVerification,
    ShipArtifact,
    VerifyArtifact,
)
from agentcouncil.autopilot.run import AutopilotRun

__all__ = ["run_ship"]


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _get_git_info() -> tuple[str, str]:
    """Return (branch_name, head_sha) from git. Returns 'unknown' on failure."""
    try:
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        head_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"
    except Exception:
        head_sha = "unknown"

    try:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        branch_name = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    except Exception:
        branch_name = "unknown"

    return branch_name, head_sha


def _check_worktree_clean() -> bool:
    """Return True if the git worktree has no uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        return result.stdout.strip() == ""
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Summary builders
# ---------------------------------------------------------------------------


def _build_readiness_summary(verify_art: VerifyArtifact) -> str:
    """Summarize verification results in a human-readable string."""
    total = len(verify_art.criteria_verdicts)
    passed_count = sum(
        1 for v in verify_art.criteria_verdicts if v.status in ("passed", "skipped")
    )
    summary = (
        f"{passed_count}/{total} acceptance criteria verified. "
        f"Overall: {verify_art.overall_status}."
    )
    failed_ids = [
        v.criterion_id
        for v in verify_art.criteria_verdicts
        if v.status == "failed"
    ]
    if failed_ids:
        summary += f" Failed criteria: {', '.join(failed_ids)}."
    return summary


def _build_release_notes(build_art: BuildArtifact) -> str:
    """Build release notes from the build artifact."""
    files = build_art.files_changed
    commit_shas = build_art.commit_shas

    notes_parts = [
        f"Changes: {len(files)} file(s) modified.",
    ]
    if files:
        files_list = ", ".join(files[:10])
        if len(files) > 10:
            files_list += f" ... and {len(files) - 10} more"
        notes_parts.append(f"Files: {files_list}.")
    if commit_shas:
        shas_str = ", ".join(commit_shas[:5])
        notes_parts.append(f"Commits: {shas_str}.")

    return " ".join(notes_parts)


# ---------------------------------------------------------------------------
# Top-level stage runner
# ---------------------------------------------------------------------------


def run_ship(
    run: AutopilotRun,
    registry: dict[str, Any],
    guidance: Optional[str] = None,
) -> ShipArtifact:
    """Ship stage runner — produces ShipArtifact readiness packet (PERS-03).

    Matches StageRunner callable signature: (run, registry, guidance) -> artifact.

    Assembles verified evidence into an auditable delivery packet.
    MVP does NOT execute deploys.
    """
    # Extract artifacts from registry
    verify_art = registry.get("verify")
    if not isinstance(verify_art, VerifyArtifact):
        # Construct minimal stub with failed status
        verify_art = VerifyArtifact(
            verify_id="verify-unknown",
            build_id="build-unknown",
            plan_id="plan-unknown",
            spec_id=run.spec_id or "spec-unknown",
            test_environment=__import__(
                "agentcouncil.autopilot.artifacts", fromlist=["VerificationEnvironment"]
            ).VerificationEnvironment(),
            criteria_verdicts=[],
            overall_status="failed",
            retry_recommendation="retry_build",
            revision_guidance="Verification artifact not found in registry.",
        )

    build_art = registry.get("build")
    if not isinstance(build_art, BuildArtifact):
        from agentcouncil.autopilot.artifacts import BuildEvidence
        build_art = BuildArtifact(
            build_id="build-unknown",
            plan_id="plan-unknown",
            spec_id=run.spec_id or "spec-unknown",
            evidence=[
                BuildEvidence(
                    task_id="unknown",
                    files_changed=[],
                    verification_notes="build artifact not found",
                )
            ],
            all_tests_passing=False,
            files_changed=[],
        )

    # Retrieve git state
    branch_name, head_sha = _get_git_info()
    worktree_clean = _check_worktree_clean()

    # Determine readiness from verification
    tests_passing = verify_art.overall_status == "passed"
    acceptance_criteria_met = verify_art.overall_status == "passed"

    # Determine recommended action and risks
    if tests_passing and acceptance_criteria_met and worktree_clean:
        recommended_action = "ship"
        blockers: list[str] = []
        remaining_risks: list[str] = []
    else:
        recommended_action = "hold"
        blockers = []

        # Collect risks from failed verdicts
        remaining_risks = [
            v.criterion_text
            for v in verify_art.criteria_verdicts
            if v.status not in ("passed", "skipped")
        ]
        if not remaining_risks:
            if not tests_passing:
                remaining_risks = ["Verification did not pass"]
            elif not worktree_clean:
                remaining_risks = ["Worktree has uncommitted changes"]
            else:
                remaining_risks = ["Verification incomplete"]

    # Build summary and notes
    readiness_summary = _build_readiness_summary(verify_art)
    release_notes = _build_release_notes(build_art)
    rollback_plan = f"git revert {head_sha}"

    # Evidence refs from verification
    evidence_refs: list[str] = [verify_art.verify_id, build_art.build_id]

    return ShipArtifact(
        ship_id=f"ship-{uuid.uuid4().hex[:8]}",
        verify_id=verify_art.verify_id,
        build_id=build_art.build_id,
        plan_id=build_art.plan_id,
        spec_id=build_art.spec_id,
        branch_name=branch_name,
        head_sha=head_sha,
        worktree_clean=worktree_clean,
        tests_passing=tests_passing,
        acceptance_criteria_met=acceptance_criteria_met,
        blockers=blockers,
        readiness_summary=readiness_summary,
        release_notes=release_notes,
        rollback_plan=rollback_plan,
        remaining_risks=remaining_risks,
        evidence_refs=evidence_refs,
        recommended_action=recommended_action,
    )
