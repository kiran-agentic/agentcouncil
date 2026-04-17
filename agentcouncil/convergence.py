"""agentcouncil.convergence — Iterative Review Workflow (CL-01 through CL-19).

Implements Convergence Loops for the review protocol: findings → fix →
scoped re-review → verify resolution → loop or approve.

Initial scope: review only (CL-14). Challenge and decide get their own
loop designs after the review contract is proven.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, List, Optional

from agentcouncil.adapters import AgentAdapter
from agentcouncil.review import review
from agentcouncil.schemas import (
    ConsensusStatus,
    ConvergenceIteration,
    ConvergenceResult,
    Finding,
    FindingIteration,
    FindingStatus,
    ReviewArtifact,
    ReviewInput,
    TranscriptMeta,
)

__all__ = ["review_loop", "MAX_ITERATIONS"]

log = logging.getLogger("agentcouncil.convergence")

# CL-12: Hard cap — never exceeded regardless of caller config
MAX_ITERATIONS = 10

_CODE_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _CODE_FENCE_RE.match(text.strip())
    return m.group(1) if m else text


def _generate_fallback_id(title: str, severity: str) -> str:
    """CL-18: Generate fallback ID from hash of title + severity."""
    h = hashlib.sha256(f"{title}:{severity}".encode()).hexdigest()[:6]
    return f"{severity[0].upper()}-{h}"


def _extract_findings(artifact: ReviewArtifact) -> list[Finding]:
    """Extract findings from a review artifact, ensuring IDs are present (CL-15, CL-18, CL-19)."""
    seen_ids: set[str] = set()
    result: list[Finding] = []

    for f in artifact.findings:
        fid = f.id
        if not fid or len(fid) > 20:
            fid = _generate_fallback_id(f.title, f.severity)

        # CL-15: Validate uniqueness within iteration
        if fid in seen_ids:
            fid = f"{fid}-{len(seen_ids)}"
        seen_ids.add(fid)

        # Reconstruct with validated ID
        result.append(f.model_copy(update={"id": fid}))

    return result


def _build_rereview_prompt(
    original_artifact: str,
    prior_findings: list[Finding],
    addressed_changes: str,
    file_paths: list[str] | None = None,
    workspace_access: str = "none",
) -> str:
    """CL-05: Build scoped re-review prompt with prior findings + change summary.

    When workspace_access is "native" and file_paths are provided, references
    file paths instead of embedding the original artifact content.
    """
    findings_text = "\n".join(
        f"- [{f.id}] {f.title} (severity: {f.severity}): {f.description}"
        for f in prior_findings
    )

    if workspace_access == "native" and file_paths:
        file_list = "\n".join(f"- {p}" for p in file_paths)
        artifact_section = f"## Original Artifact Files\nRe-read these files for the current state:\n{file_list}"
    else:
        artifact_section = f"## Original Artifact\n{original_artifact}"

    return f"""\
You are re-reviewing an artifact after the lead agent addressed your prior findings.
Focus on: (1) whether prior findings are resolved, (2) regressions from fixes.
Do NOT re-review the entire artifact from scratch.

## Prior Findings
{findings_text}

## Changes Made by Lead
{addressed_changes}

{artifact_section}

Respond with JSON containing:
- "findings": array of objects with finding_id, status (verified/reopened/open), reviewer_notes
- "approved": boolean — true if all findings are adequately addressed

Reference the original finding IDs ({', '.join(f.id for f in prior_findings)}) in your response."""


def _parse_rereview_response(
    raw: str,
    prior_findings: list[Finding],
    prior_statuses: dict[str, str],
) -> tuple[list[FindingIteration], bool]:
    """Parse the outside agent's re-review response into finding statuses.

    CL-17: Unmentioned IDs carry forward with their previous status.
    """
    cleaned = _strip_fences(raw)

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        # Can't parse — treat as all findings still open
        return [
            FindingIteration(
                finding_id=f.id,
                status=FindingStatus(prior_statuses.get(f.id, "open")),
            )
            for f in prior_findings
        ], False

    approved = data.get("approved", False)
    response_findings = data.get("findings", [])

    # Build a map of responses
    response_map: dict[str, dict] = {}
    for rf in response_findings:
        fid = rf.get("finding_id", "")
        if fid:
            response_map[fid] = rf

    # CL-17: Carry forward unmentioned IDs
    iterations: list[FindingIteration] = []
    for f in prior_findings:
        if f.id in response_map:
            rf = response_map[f.id]
            status_str = rf.get("status", prior_statuses.get(f.id, "open"))
            try:
                status = FindingStatus(status_str)
            except ValueError:
                status = FindingStatus(prior_statuses.get(f.id, "open"))
            iterations.append(FindingIteration(
                finding_id=f.id,
                status=status,
                reviewer_notes=rf.get("reviewer_notes"),
            ))
        else:
            # CL-17: unmentioned — carry forward
            iterations.append(FindingIteration(
                finding_id=f.id,
                status=FindingStatus(prior_statuses.get(f.id, "open")),
            ))

    return iterations, approved


async def review_loop(
    artifact: str,
    artifact_type: str = "code",
    outside_adapter: AgentAdapter | None = None,
    lead_adapter: AgentAdapter | None = None,
    review_objective: Optional[str] = None,
    focus_areas: Optional[list[str]] = None,
    max_iterations: int = 3,
    on_event: Optional[Any] = None,
    outside_meta: Optional[TranscriptMeta] = None,
    file_paths: Optional[list[str]] = None,
    workspace_access: str = "none",
    prior_review_context: Optional[str] = None,
) -> ConvergenceResult:
    """Run an iterative review convergence loop (CL-01, CL-02).

    Args:
        artifact: Text content to review (used as fallback when workspace_access
            is not "native" or file_paths is empty).
        artifact_type: Type of artifact (code, design, plan, etc.).
        outside_adapter: AgentAdapter for the outside reviewer.
        lead_adapter: AgentAdapter for the lead agent.
        review_objective: Optional focus for the review.
        focus_areas: Optional specific areas to examine.
        max_iterations: Maximum review iterations (default 3, CL-12 hard cap 10).
        on_event: Optional event callback.
        outside_meta: Optional provenance metadata.
        file_paths: File paths for agents with native workspace access to read directly.
        workspace_access: Backend workspace capability ("native", "assisted", "none").

    Returns:
        ConvergenceResult with iteration history, final findings, and exit reason.
    """
    # CL-12: Hard cap
    effective_max = min(max_iterations, MAX_ITERATIONS)

    iterations: list[ConvergenceIteration] = []
    current_findings: list[Finding] = []
    finding_statuses: dict[str, str] = {}  # finding_id -> current status

    # Iteration 1: Run initial review
    review_input = ReviewInput(
        artifact=artifact,
        artifact_type=artifact_type,
        review_objective=review_objective,
        focus_areas=focus_areas or [],
        rounds=1,
        file_paths=file_paths or [],
        prior_review_context=prior_review_context,
    )

    review_result = await review(
        review_input, outside_adapter, lead_adapter,
        on_event=on_event, outside_meta=outside_meta,
        workspace_access=workspace_access,
    )

    # Extract findings from initial review
    current_findings = _extract_findings(review_result.artifact)

    # Record iteration 1
    iteration_findings = [
        FindingIteration(finding_id=f.id, status=FindingStatus.open)
        for f in current_findings
    ]
    iterations.append(ConvergenceIteration(
        iteration=1,
        findings=iteration_findings,
    ))
    finding_statuses = {f.id: "open" for f in current_findings}

    # Check if no findings — immediate pass
    if not current_findings:
        return ConvergenceResult(
            iterations=iterations,
            final_findings=[],
            total_iterations=1,
            exit_reason="all_verified",
            final_verdict="pass",
        )

    # Native-workspace short-circuit: when the outside agent reads files directly,
    # the inner loop can't converge — the lead only *describes* fixes, it doesn't
    # apply them to disk, so the reviewer sees unchanged files on re-review and
    # returns the same findings. In that mode, convergence happens outside this
    # function: caller applies real fixes, then re-invokes review_loop.
    if workspace_access == "native" and file_paths:
        return ConvergenceResult(
            iterations=iterations,
            final_findings=current_findings,
            total_iterations=1,
            exit_reason="native_workspace_single_pass",
            final_verdict=_derive_verdict(finding_statuses),
        )

    # Iterations 2..N: fix-describe → scoped re-review → update statuses.
    # Runs only for text-artifact reviews (workspace_access != "native"), where
    # the lead's described changes are embedded in the re-review prompt and the
    # outside session accumulates context across turns.
    for iter_num in range(2, effective_max + 1):
        open_findings = [
            f for f in current_findings
            if finding_statuses.get(f.id) in ("open", "reopened")
        ]
        if not open_findings:
            break

        findings_summary = "\n".join(
            f"- [{f.id}] {f.title} ({f.severity}): {f.description}"
            for f in open_findings
        )
        lead_prompt = (
            f"The following findings need to be addressed:\n{findings_summary}\n\n"
            f"Describe what changes you would make to fix each finding."
        )
        from agentcouncil.adapters import AdapterError

        try:
            addressed_changes = await lead_adapter.acall(lead_prompt)
        except AdapterError as e:
            log.warning("lead failed in convergence iteration %d: %s", iter_num, e)
            addressed_changes = f"Lead error: {e}"

        rereview_prompt = _build_rereview_prompt(
            artifact, open_findings, addressed_changes,
            file_paths=file_paths,
            workspace_access=workspace_access,
        )
        try:
            rereview_response = await outside_adapter.acall(rereview_prompt)
        except AdapterError as e:
            log.warning("outside failed in convergence re-review %d: %s", iter_num, e)
            break

        iter_findings, approved = _parse_rereview_response(
            rereview_response, current_findings, finding_statuses,
        )
        for fi in iter_findings:
            finding_statuses[fi.finding_id] = fi.status

        iterations.append(ConvergenceIteration(
            iteration=iter_num,
            findings=iter_findings,
            approved=approved,
        ))

        if approved:
            return ConvergenceResult(
                iterations=iterations,
                final_findings=current_findings,
                total_iterations=iter_num,
                exit_reason="approved",
                final_verdict=_derive_verdict(finding_statuses),
            )

        if all(s in ("verified", "wont_fix") for s in finding_statuses.values()):
            return ConvergenceResult(
                iterations=iterations,
                final_findings=current_findings,
                total_iterations=iter_num,
                exit_reason="all_verified",
                final_verdict=_derive_verdict(finding_statuses),
            )

    return ConvergenceResult(
        iterations=iterations,
        final_findings=current_findings,
        total_iterations=len(iterations),
        exit_reason="max_iterations",
        final_verdict=_derive_verdict(finding_statuses),
    )


def _derive_verdict(statuses: dict[str, str]) -> str:
    """Derive final verdict from finding statuses."""
    if not statuses:
        return "pass"
    if all(s in ("verified", "wont_fix") for s in statuses.values()):
        return "pass"
    if any(s in ("open", "reopened") for s in statuses.values()):
        return "revise"
    return "pass"
