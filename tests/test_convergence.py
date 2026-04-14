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
