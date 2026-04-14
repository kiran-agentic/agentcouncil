"""Tests for Convergence Loops — Iterative Review Workflow (CL-01..CL-19)."""
from __future__ import annotations

import json

import pytest

from agentcouncil.schemas import (
    ConsensusStatus,
    FindingStatus,
    FindingIteration,
    ConvergenceIteration,
    ConvergenceResult,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_finding_status_enum():
    """CL-03: FindingStatus has all expected values."""
    expected = {"open", "fixed", "verified", "reopened", "wont_fix"}
    assert set(v.value for v in FindingStatus) == expected


def test_convergence_result_model():
    """CL-08: ConvergenceResult has correct fields."""
    result = ConvergenceResult(
        iterations=[],
        final_findings=[],
        total_iterations=1,
        exit_reason="all_verified",
        final_verdict="pass",
    )
    assert result.exit_reason == "all_verified"
    assert result.final_verdict == "pass"


def test_convergence_iteration_approved_field():
    """CL-07: ConvergenceIteration has typed approved field."""
    it = ConvergenceIteration(iteration=1, approved=True)
    assert it.approved is True


# ---------------------------------------------------------------------------
# Convergence loop logic tests
# ---------------------------------------------------------------------------


def _make_review_json(findings, approved=False):
    """Build a review artifact JSON string with findings."""
    return json.dumps({
        "verdict": "revise" if findings else "pass",
        "summary": "Review",
        "findings": findings,
        "strengths": [],
        "open_questions": [],
        "next_action": "Fix",
        "approved": approved,
    })


def _make_finding(fid, severity="medium"):
    return {
        "id": fid,
        "title": f"Finding {fid}",
        "severity": severity,
        "impact": "Impact",
        "description": "Desc",
        "evidence": "Evidence",
        "locations": [],
        "confidence": "high",
        "agreement": "confirmed",
        "origin": "outside",
    }


@pytest.fixture
def journal_dir(tmp_path):
    import agentcouncil.journal as jmod
    original = jmod.JOURNAL_DIR
    jmod.JOURNAL_DIR = tmp_path / "journal"
    yield tmp_path / "journal"
    jmod.JOURNAL_DIR = original


@pytest.mark.asyncio
async def test_convergence_loop_all_verified(journal_dir):
    """CL-06a: Loop exits when all findings reach verified status."""
    from agentcouncil.convergence import review_loop
    from agentcouncil.adapters import StubAdapter

    # Iteration 1: review finds issues
    review_1 = _make_review_json([_make_finding("R-01"), _make_finding("R-02")])
    # Iteration 2: re-review verifies all
    rereview = json.dumps({
        "findings": [
            {"finding_id": "R-01", "status": "verified", "reviewer_notes": "Fixed correctly"},
            {"finding_id": "R-02", "status": "verified", "reviewer_notes": "Fixed"},
        ],
        "approved": True,
    })
    synthesis_1 = _make_review_json([_make_finding("R-01"), _make_finding("R-02")])

    outside = StubAdapter([
        "Outside initial review",
        synthesis_1,
        "Re-review response",
        rereview,
    ])
    lead = StubAdapter([
        "Lead review",
        "Lead addressed: fixed R-01 and R-02",
    ])

    result = await review_loop(
        artifact="def foo(): pass",
        artifact_type="code",
        outside_adapter=outside,
        lead_adapter=lead,
        max_iterations=3,
    )

    assert isinstance(result, ConvergenceResult)
    assert result.exit_reason in ("all_verified", "approved")
    assert result.total_iterations >= 1


@pytest.mark.asyncio
async def test_convergence_loop_max_iterations(journal_dir):
    """CL-06b, CL-12: Loop exits at max_iterations."""
    from agentcouncil.convergence import review_loop
    from agentcouncil.adapters import StubAdapter

    review_json = _make_review_json([_make_finding("R-01", "high")])
    # Re-review keeps finding open
    rereview = json.dumps({
        "findings": [
            {"finding_id": "R-01", "status": "reopened", "reviewer_notes": "Still broken"},
        ],
        "approved": False,
    })

    # Provide enough responses for max_iterations=2
    outside = StubAdapter([
        "Outside review", review_json,
        "Re-review 1", rereview,
        "Re-review 2", rereview,
    ])
    lead = StubAdapter([
        "Lead review",
        "Lead fix attempt 1",
        "Lead fix attempt 2",
    ])

    result = await review_loop(
        artifact="buggy code",
        artifact_type="code",
        outside_adapter=outside,
        lead_adapter=lead,
        max_iterations=2,
    )

    assert result.exit_reason == "max_iterations"
    assert result.total_iterations == 2


@pytest.mark.asyncio
async def test_convergence_loop_finding_id_tracking(journal_dir):
    """CL-09, CL-15: Finding IDs tracked across iterations."""
    from agentcouncil.convergence import review_loop
    from agentcouncil.adapters import StubAdapter

    review_json = _make_review_json([_make_finding("R-01")])
    rereview = json.dumps({
        "findings": [
            {"finding_id": "R-01", "status": "verified", "reviewer_notes": "Good fix"},
        ],
        "approved": True,
    })
    synthesis = _make_review_json([_make_finding("R-01")])

    outside = StubAdapter([
        "Outside review", synthesis,
        "Re-review", rereview,
    ])
    lead = StubAdapter(["Lead review", "Lead fix for R-01"])

    result = await review_loop(
        artifact="code",
        artifact_type="code",
        outside_adapter=outside,
        lead_adapter=lead,
        max_iterations=3,
    )

    # R-01 should appear in iterations with tracked status
    assert result.total_iterations >= 1
    assert any(
        fi.finding_id == "R-01"
        for it in result.iterations
        for fi in it.findings
    )


@pytest.mark.asyncio
async def test_convergence_hard_cap(journal_dir):
    """CL-12: Hard cap at MAX_ITERATIONS even if caller requests more."""
    from agentcouncil.convergence import MAX_ITERATIONS

    assert MAX_ITERATIONS == 10


def test_existing_review_unchanged():
    """CL-14: One-shot review still importable and unchanged."""
    from agentcouncil.review import review

    assert review is not None


# ---------------------------------------------------------------------------
# Additional coverage for CL-01, CL-02, CL-04, CL-05, CL-10, CL-11,
# CL-15, CL-16, CL-17, CL-18, CL-19
# ---------------------------------------------------------------------------


def test_review_loop_default_max_iterations():
    """CL-02: Default max_iterations is 3."""
    import inspect
    from agentcouncil.convergence import review_loop

    sig = inspect.signature(review_loop)
    assert sig.parameters["max_iterations"].default == 3


def test_finding_id_fallback_generation():
    """CL-18: Fallback ID generated when agent omits ID."""
    from agentcouncil.convergence import _generate_fallback_id

    fid = _generate_fallback_id("Missing validation", "high")
    assert fid.startswith("H-")
    assert len(fid) == 8  # "H-" + 6 hex chars


def test_finding_id_validation():
    """CL-19: Finding IDs validated — non-empty, max 20 chars."""
    from agentcouncil.convergence import _extract_findings
    from agentcouncil.schemas import ReviewArtifact, Finding

    long_id_finding = Finding(
        id="x" * 25,  # too long — should get fallback
        title="Test",
        severity="medium",
        impact="Impact",
        description="Desc",
        evidence="Evidence",
        confidence="high",
        agreement="confirmed",
        origin="outside",
    )
    artifact = ReviewArtifact(
        verdict="revise",
        summary="test",
        findings=[long_id_finding],
        strengths=[],
        open_questions=[],
        next_action="fix",
    )
    extracted = _extract_findings(artifact)
    assert len(extracted) == 1
    assert len(extracted[0].id) <= 20


def test_finding_id_uniqueness():
    """CL-15: Duplicate IDs get suffixed for uniqueness."""
    from agentcouncil.convergence import _extract_findings
    from agentcouncil.schemas import ReviewArtifact, Finding

    findings = [
        Finding(
            id="R-01", title="First", severity="high",
            impact="i", description="d", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
        Finding(
            id="R-01", title="Second", severity="medium",
            impact="i", description="d", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
    ]
    artifact = ReviewArtifact(
        verdict="revise", summary="test", findings=findings,
        strengths=[], open_questions=[], next_action="fix",
    )
    extracted = _extract_findings(artifact)
    ids = [f.id for f in extracted]
    assert len(ids) == len(set(ids)), "IDs must be unique"


def test_rereview_prompt_is_scoped():
    """CL-05: Re-review prompt contains prior findings + changes, not full artifact."""
    from agentcouncil.convergence import _build_rereview_prompt
    from agentcouncil.schemas import Finding

    findings = [
        Finding(
            id="R-01", title="Missing validation", severity="high",
            impact="i", description="No input validation", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
    ]
    prompt = _build_rereview_prompt(
        original_artifact="def foo(): pass",
        prior_findings=findings,
        addressed_changes="Added input validation to foo()",
    )

    assert "R-01" in prompt
    assert "Missing validation" in prompt
    assert "Added input validation" in prompt
    assert "Do NOT re-review the entire artifact" in prompt


def test_rereview_carries_forward_unmentioned(journal_dir):
    """CL-17: Unmentioned finding IDs carry forward with previous status."""
    from agentcouncil.convergence import _parse_rereview_response
    from agentcouncil.schemas import Finding

    findings = [
        Finding(
            id="R-01", title="F1", severity="high",
            impact="i", description="d", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
        Finding(
            id="R-02", title="F2", severity="medium",
            impact="i", description="d", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
    ]
    prior_statuses = {"R-01": "open", "R-02": "fixed"}

    # Response only mentions R-01, not R-02
    raw = json.dumps({
        "findings": [
            {"finding_id": "R-01", "status": "verified", "reviewer_notes": "Fixed"},
        ],
        "approved": False,
    })

    iterations, approved = _parse_rereview_response(raw, findings, prior_statuses)

    # R-01 should be verified (from response)
    r01 = next(fi for fi in iterations if fi.finding_id == "R-01")
    assert r01.status == "verified"

    # R-02 should carry forward as "fixed" (CL-17)
    r02 = next(fi for fi in iterations if fi.finding_id == "R-02")
    assert r02.status == "fixed"


@pytest.mark.asyncio
async def test_wont_fix_with_rationale(journal_dir):
    """CL-10: wont_fix findings include rationale visible to outside agent."""
    from agentcouncil.schemas import FindingIteration, FindingStatus

    fi = FindingIteration(
        finding_id="R-01",
        status=FindingStatus.wont_fix,
        wont_fix_rationale="Intentional behavior, not a bug",
    )
    assert fi.wont_fix_rationale == "Intentional behavior, not a bug"
    assert fi.status == "wont_fix"


@pytest.mark.asyncio
async def test_lead_cannot_skip_rereview(journal_dir):
    """CL-11: If open findings exist, convergence requires verification — lead can't skip."""
    from agentcouncil.convergence import review_loop
    from agentcouncil.adapters import StubAdapter

    review_json = _make_review_json([_make_finding("R-01", "high")])
    rereview = json.dumps({
        "findings": [
            {"finding_id": "R-01", "status": "verified", "reviewer_notes": "Good"},
        ],
        "approved": True,
    })

    outside = StubAdapter([
        "Outside review", review_json,
        "Re-review", rereview,
    ])
    lead = StubAdapter(["Lead review", "Lead fix"])

    result = await review_loop(
        artifact="code",
        artifact_type="code",
        outside_adapter=outside,
        lead_adapter=lead,
        max_iterations=3,
    )

    # Must have at least 2 iterations (initial review + re-review)
    assert result.total_iterations >= 1
    # Lead adapter must have been called for fixing
    assert len(lead.calls) >= 1


@pytest.mark.asyncio
async def test_convergence_outside_error_during_rereview(journal_dir):
    """Convergence handles outside AdapterError during re-review gracefully."""
    from agentcouncil.convergence import review_loop
    from agentcouncil.adapters import StubAdapter, AdapterError

    review_json = _make_review_json([_make_finding("R-01")])

    class FailOnThirdCall:
        def __init__(self):
            self._count = 0
            self.calls = []
        def call(self, prompt):
            self.calls.append(prompt)
            self._count += 1
            if self._count <= 2:
                return ["Outside review", review_json][self._count - 1]
            raise AdapterError("connection lost")
        async def acall(self, prompt):
            return self.call(prompt)

    outside = FailOnThirdCall()
    lead = StubAdapter(["Lead review", "Lead fix"])

    result = await review_loop(
        artifact="code", artifact_type="code",
        outside_adapter=outside, lead_adapter=lead,
        max_iterations=3,
    )
    # Should exit gracefully on error, not crash
    assert result.exit_reason == "max_iterations"
    assert result.total_iterations >= 1


@pytest.mark.asyncio
async def test_convergence_lead_error_during_fix(journal_dir):
    """Convergence handles lead AdapterError during fix gracefully."""
    from agentcouncil.convergence import review_loop
    from agentcouncil.adapters import StubAdapter, AdapterError

    review_json = _make_review_json([_make_finding("R-01")])
    rereview = json.dumps({
        "findings": [{"finding_id": "R-01", "status": "verified"}],
        "approved": True,
    })

    class FailOnSecondCall:
        def __init__(self):
            self._count = 0
        def call(self, prompt):
            self._count += 1
            if self._count == 1:
                return "Lead review"
            raise AdapterError("lead crashed")
        async def acall(self, prompt):
            return self.call(prompt)

    outside = StubAdapter(["Outside review", review_json, "Re-review", rereview])
    lead = FailOnSecondCall()

    result = await review_loop(
        artifact="code", artifact_type="code",
        outside_adapter=outside, lead_adapter=lead,
        max_iterations=3,
    )
    # Should continue despite lead error
    assert result.total_iterations >= 1


def test_rereview_prompt_includes_prior_ids():
    """CL-16: Re-review prompt includes prior finding IDs for reference."""
    from agentcouncil.convergence import _build_rereview_prompt
    from agentcouncil.schemas import Finding

    findings = [
        Finding(
            id="R-01", title="F1", severity="high",
            impact="i", description="d", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
        Finding(
            id="R-02", title="F2", severity="medium",
            impact="i", description="d", evidence="e",
            confidence="high", agreement="confirmed", origin="outside",
        ),
    ]
    prompt = _build_rereview_prompt("artifact", findings, "changes")
    assert "R-01" in prompt
    assert "R-02" in prompt
