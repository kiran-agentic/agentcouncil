from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcouncil.schemas import (
    ChallengeArtifact,
    ConsensusArtifact,
    ConvergenceResult,
    DecideArtifact,
    FailureMode,
    Finding,
    OptionAssessment,
    ReviewArtifact,
)

# Import the class under test -- will FAIL until normalizer.py is created
from agentcouncil.autopilot.normalizer import GateNormalizer


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_finding(**overrides) -> Finding:
    defaults = {
        "id": "f-1",
        "title": "Some finding",
        "severity": "high",
        "impact": "breaks things",
        "description": "The thing is broken",
        "evidence": "see line 42",
        "confidence": "high",
        "agreement": "confirmed",
        "origin": "outside",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_failure_mode(**overrides) -> FailureMode:
    defaults = {
        "id": "fm-1",
        "assumption_ref": "A-1",
        "description": "The thing will fail under load",
        "severity": "high",
        "impact": "service outage",
        "confidence": "high",
        "disposition": "must_harden",
    }
    defaults.update(overrides)
    return FailureMode(**defaults)


def _make_consensus(**overrides) -> ConsensusArtifact:
    defaults = {
        "recommended_direction": "go with option A",
        "agreement_points": ["agree on scope"],
        "disagreement_points": [],
        "rejected_alternatives": [],
        "open_risks": [],
        "next_action": "implement option A",
        "status": "consensus",
    }
    defaults.update(overrides)
    return ConsensusArtifact(**defaults)


def _make_review(**overrides) -> ReviewArtifact:
    defaults = {
        "verdict": "pass",
        "summary": "Looks good",
        "findings": [],
        "next_action": "proceed",
    }
    defaults.update(overrides)
    return ReviewArtifact(**defaults)


def _make_convergence(**overrides) -> ConvergenceResult:
    defaults = {
        "iterations": [],
        "final_findings": [],
        "total_iterations": 1,
        "exit_reason": "all_verified",
        "final_verdict": "pass",
    }
    defaults.update(overrides)
    return ConvergenceResult(**defaults)


def _make_challenge(**overrides) -> ChallengeArtifact:
    """Build a ChallengeArtifact; default readiness=ready (no failure_modes needed)."""
    defaults = {
        "readiness": "ready",
        "summary": "System is ready",
        "failure_modes": [],
        "next_action": "proceed",
    }
    defaults.update(overrides)
    return ChallengeArtifact(**defaults)


def _make_option_assessment(option_id: str, disposition: str) -> OptionAssessment:
    return OptionAssessment(
        option_id=option_id,
        pros=["good thing"],
        cons=[],
        disposition=disposition,
        confidence="high",
    )


def _make_decide(**overrides) -> DecideArtifact:
    """
    Build a valid DecideArtifact.

    outcome="decided" requires winner_option_id + one selected assessment.
    outcome="experiment" requires experiment_plan + one viable assessment.
    outcome="deferred" requires defer_reason (no selected assessments).
    Default: decided.
    """
    outcome = overrides.get("outcome", "decided")

    if outcome == "decided":
        defaults: dict = {
            "outcome": "decided",
            "winner_option_id": "opt-a",
            "decision_summary": "We decided on option A",
            "option_assessments": [_make_option_assessment("opt-a", "selected")],
            "next_action": "implement",
        }
    elif outcome == "experiment":
        defaults = {
            "outcome": "experiment",
            "experiment_plan": "run a canary deployment",
            "decision_summary": "experiment needed",
            "option_assessments": [_make_option_assessment("opt-a", "viable")],
            "next_action": "set up experiment",
        }
    else:  # deferred
        defaults = {
            "outcome": "deferred",
            "defer_reason": "insufficient data",
            "decision_summary": "decision deferred",
            "option_assessments": [],
            "next_action": "gather data",
        }

    defaults.update(overrides)
    return DecideArtifact(**defaults)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_normalizer = GateNormalizer()


# ---------------------------------------------------------------------------
# Brainstorm protocol tests
# ---------------------------------------------------------------------------


def test_brainstorm_consensus_advances():
    artifact = _make_consensus(status="consensus")
    decision = _normalizer.normalize("brainstorm", artifact)
    assert decision.decision == "advance"
    assert decision.protocol_type == "brainstorm"


def test_brainstorm_consensus_with_reservations_advances():
    artifact = _make_consensus(status="consensus_with_reservations")
    decision = _normalizer.normalize("brainstorm", artifact)
    assert decision.decision == "advance"
    assert decision.protocol_type == "brainstorm"


def test_brainstorm_unresolved_blocks():
    artifact = _make_consensus(status="unresolved_disagreement")
    decision = _normalizer.normalize("brainstorm", artifact)
    assert decision.decision == "block"
    assert decision.protocol_type == "brainstorm"


def test_brainstorm_partial_failure_blocks():
    artifact = _make_consensus(status="partial_failure")
    decision = _normalizer.normalize("brainstorm", artifact)
    assert decision.decision == "block"
    assert decision.protocol_type == "brainstorm"


# ---------------------------------------------------------------------------
# Review protocol tests
# ---------------------------------------------------------------------------


def test_review_pass_advances():
    artifact = _make_review(verdict="pass")
    decision = _normalizer.normalize("review", artifact)
    assert decision.decision == "advance"
    assert decision.protocol_type == "review"


def test_review_revise_produces_guidance():
    finding = _make_finding(severity="high", description="Critical logic error")
    artifact = _make_review(
        verdict="revise",
        findings=[finding],
        next_action="fix the logic error",
    )
    decision = _normalizer.normalize("review", artifact)
    assert decision.decision == "revise"
    assert decision.revision_guidance is not None
    assert len(decision.revision_guidance) > 0
    # Guidance should reference finding description
    assert "Critical logic error" in decision.revision_guidance


def test_review_revise_fallback_to_next_action():
    artifact = _make_review(
        verdict="revise",
        findings=[],
        next_action="fix X",
    )
    decision = _normalizer.normalize("review", artifact)
    assert decision.decision == "revise"
    assert decision.revision_guidance is not None
    assert "fix X" in decision.revision_guidance


def test_review_escalate_blocks():
    artifact = _make_review(verdict="escalate")
    decision = _normalizer.normalize("review", artifact)
    assert decision.decision == "block"
    assert decision.protocol_type == "review"


# ---------------------------------------------------------------------------
# Review loop (ConvergenceResult) protocol tests
# ---------------------------------------------------------------------------


def test_review_loop_pass_advances():
    artifact = _make_convergence(final_verdict="pass")
    decision = _normalizer.normalize("review_loop", artifact)
    assert decision.decision == "advance"
    assert decision.protocol_type == "review_loop"


def test_review_loop_revise_produces_guidance():
    finding = _make_finding(description="Unresolved issue from iteration 2")
    artifact = _make_convergence(
        final_verdict="revise",
        final_findings=[finding],
        exit_reason="max_iterations",
    )
    decision = _normalizer.normalize("review_loop", artifact)
    assert decision.decision == "revise"
    assert decision.revision_guidance is not None
    assert "Unresolved issue from iteration 2" in decision.revision_guidance


def test_review_loop_revise_fallback_to_exit_reason():
    artifact = _make_convergence(
        final_verdict="revise",
        final_findings=[],
        exit_reason="max_iterations",
    )
    decision = _normalizer.normalize("review_loop", artifact)
    assert decision.decision == "revise"
    assert decision.revision_guidance is not None
    assert "max_iterations" in decision.revision_guidance


def test_review_loop_escalate_blocks():
    artifact = _make_convergence(final_verdict="escalate")
    decision = _normalizer.normalize("review_loop", artifact)
    assert decision.decision == "block"
    assert decision.protocol_type == "review_loop"


# ---------------------------------------------------------------------------
# Challenge protocol tests
# ---------------------------------------------------------------------------


def test_challenge_ready_advances():
    artifact = _make_challenge(readiness="ready")
    decision = _normalizer.normalize("challenge", artifact)
    assert decision.decision == "advance"
    assert decision.protocol_type == "challenge"


def test_challenge_needs_hardening_revises():
    fm = _make_failure_mode(disposition="must_harden", description="Memory leak under load")
    artifact = _make_challenge(
        readiness="needs_hardening",
        failure_modes=[fm],
    )
    decision = _normalizer.normalize("challenge", artifact)
    assert decision.decision == "revise"
    assert decision.revision_guidance is not None
    assert "Memory leak under load" in decision.revision_guidance


def test_challenge_not_ready_blocks():
    fm = _make_failure_mode(disposition="must_harden", description="Total system failure")
    artifact = _make_challenge(
        readiness="not_ready",
        failure_modes=[fm],
    )
    decision = _normalizer.normalize("challenge", artifact)
    assert decision.decision == "block"
    assert decision.protocol_type == "challenge"


# ---------------------------------------------------------------------------
# Decide protocol tests
# ---------------------------------------------------------------------------


def test_decide_decided_advances():
    artifact = _make_decide(outcome="decided")
    decision = _normalizer.normalize("decide", artifact)
    assert decision.decision == "advance"
    assert decision.protocol_type == "decide"


def test_decide_experiment_revises():
    artifact = _make_decide(outcome="experiment", experiment_plan="try X")
    decision = _normalizer.normalize("decide", artifact)
    assert decision.decision == "revise"
    assert decision.revision_guidance == "try X"


def test_decide_deferred_blocks():
    artifact = _make_decide(outcome="deferred")
    decision = _normalizer.normalize("decide", artifact)
    assert decision.decision == "block"
    assert decision.protocol_type == "decide"


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


def test_unknown_protocol_blocks_no_exception():
    """Unknown protocol type must return decision=block, never raise."""
    artifact = _make_consensus()
    decision = _normalizer.normalize("unknown_type", artifact)
    assert decision.decision == "block"
    assert decision.rationale is not None
    assert len(decision.rationale) > 0


def test_mismatched_type_blocks_no_exception():
    """Mismatched protocol type and artifact must return block, never raise."""
    artifact = _make_consensus()  # ConsensusArtifact but protocol_type="review"
    decision = _normalizer.normalize("review", artifact)
    assert decision.decision == "block"
    assert decision.rationale is not None


# ---------------------------------------------------------------------------
# Session ID propagation tests
# ---------------------------------------------------------------------------


def test_session_id_propagates():
    artifact = _make_consensus()
    decision = _normalizer.normalize("brainstorm", artifact, session_id="sess-42")
    assert decision.protocol_session_id == "sess-42"


def test_session_id_defaults_to_unknown():
    artifact = _make_consensus()
    decision = _normalizer.normalize("brainstorm", artifact)
    assert decision.protocol_session_id == "unknown"
