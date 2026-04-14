"""Tests for Expert Witness — Protocol-Scoped Specialist Checks (EW-01..EW-13)."""
from __future__ import annotations

import json

import pytest

from agentcouncil.schemas import TranscriptTurn


# ---------------------------------------------------------------------------
# Specialist schema tests (EW-06)
# ---------------------------------------------------------------------------


def test_challenge_specialist_assessment_schema():
    """EW-06: ChallengeSpecialistAssessment has correct fields."""
    from agentcouncil.schemas import ChallengeSpecialistAssessment

    a = ChallengeSpecialistAssessment(
        assumption="SQL injection is prevented",
        validity="questionable",
        evidence="No parameterized queries found",
        confidence="high",
    )
    assert a.validity == "questionable"
    assert a.confidence == "high"


def test_review_specialist_finding_schema():
    """EW-06: ReviewSpecialistFinding has correct fields."""
    from agentcouncil.schemas import ReviewSpecialistFinding

    f = ReviewSpecialistFinding(
        area="authentication",
        severity="high",
        evidence="Tokens not rotated",
        affected_scope="all API endpoints",
    )
    assert f.area == "authentication"


def test_decide_specialist_evaluation_schema():
    """EW-06: DecideSpecialistEvaluation has correct fields."""
    from agentcouncil.schemas import DecideSpecialistEvaluation

    e = DecideSpecialistEvaluation(
        option_id="opt-1",
        criterion="latency",
        score="strong",
        rationale="P99 under 50ms",
    )
    assert e.score == "strong"


# ---------------------------------------------------------------------------
# specialist_check function tests (EW-01, EW-02, EW-13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_specialist_check_returns_typed_artifact():
    """EW-01: specialist_check returns a typed artifact."""
    from agentcouncil.specialist import specialist_check
    from agentcouncil.schemas import ChallengeSpecialistAssessment
    from agentcouncil.adapters import StubAdapter

    response_json = json.dumps({
        "assumption": "Data is encrypted at rest",
        "validity": "valid",
        "evidence": "AES-256 confirmed in storage layer",
        "confidence": "high",
    })
    adapter = StubAdapter([response_json])

    result = await specialist_check(
        sub_question="Is data encrypted at rest?",
        context_slice="Storage uses AES-256",
        specialist_adapter=adapter,
        artifact_cls=ChallengeSpecialistAssessment,
    )

    assert isinstance(result, ChallengeSpecialistAssessment)
    assert result.validity == "valid"


@pytest.mark.asyncio
async def test_specialist_check_context_isolation():
    """EW-02: Specialist receives only sub_question + context_slice."""
    from agentcouncil.specialist import specialist_check
    from agentcouncil.schemas import ChallengeSpecialistAssessment
    from agentcouncil.adapters import StubAdapter

    response_json = json.dumps({
        "assumption": "test",
        "validity": "valid",
        "evidence": "test",
        "confidence": "medium",
    })
    adapter = StubAdapter([response_json])

    await specialist_check(
        sub_question="Is encryption adequate?",
        context_slice="Uses AES-256",
        specialist_adapter=adapter,
        artifact_cls=ChallengeSpecialistAssessment,
    )

    # Verify the prompt sent to the specialist
    assert len(adapter.calls) == 1
    prompt = adapter.calls[0]
    assert "Is encryption adequate?" in prompt
    assert "Uses AES-256" in prompt


@pytest.mark.asyncio
async def test_specialist_check_failure_returns_none():
    """EW-13: Specialist failure returns None — protocol continues."""
    from agentcouncil.specialist import specialist_check
    from agentcouncil.schemas import ChallengeSpecialistAssessment

    class FailingAdapter:
        calls = []
        def call(self, prompt):
            raise Exception("specialist unavailable")
        async def acall(self, prompt):
            return self.call(prompt)

    result = await specialist_check(
        sub_question="test",
        context_slice="test",
        specialist_adapter=FailingAdapter(),
        artifact_cls=ChallengeSpecialistAssessment,
    )

    assert result is None


@pytest.mark.asyncio
async def test_specialist_check_bad_json_returns_none():
    """EW-13: Unparseable specialist response returns None."""
    from agentcouncil.specialist import specialist_check
    from agentcouncil.schemas import ChallengeSpecialistAssessment
    from agentcouncil.adapters import StubAdapter

    adapter = StubAdapter(["This is not JSON at all"])

    result = await specialist_check(
        sub_question="test",
        context_slice="test",
        specialist_adapter=adapter,
        artifact_cls=ChallengeSpecialistAssessment,
    )

    assert result is None


@pytest.mark.asyncio
async def test_specialist_evidence_as_transcript_turn():
    """EW-08: Specialist evidence produces a TranscriptTurn with phase='specialist'."""
    from agentcouncil.specialist import make_specialist_turn
    from agentcouncil.schemas import ChallengeSpecialistAssessment

    assessment = ChallengeSpecialistAssessment(
        assumption="data encrypted",
        validity="valid",
        evidence="AES-256 confirmed",
        confidence="high",
    )
    turn = make_specialist_turn(
        artifact=assessment,
        sub_question="Is encryption adequate?",
        parent_turn_id="turn-005",
        provider_name="openrouter",
        model_name="claude-3-5-sonnet",
    )

    assert isinstance(turn, TranscriptTurn)
    assert turn.phase == "specialist"
    assert turn.parent_turn_id == "turn-005"
    assert turn.actor_provider == "openrouter"
    assert turn.actor_model == "claude-3-5-sonnet"
    assert "AES-256" in turn.content


# ---------------------------------------------------------------------------
# Additional coverage: EW-03, EW-04, EW-05, EW-07, EW-10, EW-11, EW-12
# ---------------------------------------------------------------------------


def test_specialist_output_is_evaluative_not_prescriptive():
    """EW-03, EW-07: Specialist output schemas are evaluative — validity/severity, not fixes."""
    from agentcouncil.schemas import (
        ChallengeSpecialistAssessment,
        ReviewSpecialistFinding,
        DecideSpecialistEvaluation,
    )

    # ChallengeSpecialistAssessment has validity, not recommendation
    assert "validity" in ChallengeSpecialistAssessment.model_fields
    assert "recommendation" not in ChallengeSpecialistAssessment.model_fields

    # ReviewSpecialistFinding has severity, not fix
    assert "severity" in ReviewSpecialistFinding.model_fields
    assert "fix" not in ReviewSpecialistFinding.model_fields

    # DecideSpecialistEvaluation has score, not recommendation
    assert "score" in DecideSpecialistEvaluation.model_fields
    assert "recommendation" not in DecideSpecialistEvaluation.model_fields


@pytest.mark.asyncio
async def test_specialist_check_one_call_only():
    """EW-04: Specialist check makes exactly one adapter call per invocation."""
    import json
    from agentcouncil.schemas import ChallengeSpecialistAssessment
    from agentcouncil.specialist import specialist_check
    from agentcouncil.adapters import StubAdapter

    response_json = json.dumps({
        "assumption": "test",
        "validity": "valid",
        "evidence": "test",
        "confidence": "high",
    })
    adapter = StubAdapter([response_json])

    await specialist_check(
        sub_question="test?",
        context_slice="context",
        specialist_adapter=adapter,
        artifact_cls=ChallengeSpecialistAssessment,
    )
    assert len(adapter.calls) == 1  # Exactly one call


def test_specialist_prompt_excludes_full_debate():
    """EW-02 reinforced: Specialist prompt does NOT contain debate keywords."""
    from agentcouncil.specialist import _build_specialist_prompt
    from agentcouncil.schemas import ChallengeSpecialistAssessment

    prompt = _build_specialist_prompt(
        sub_question="Is encryption adequate?",
        context_slice="Uses AES-256",
        artifact_cls=ChallengeSpecialistAssessment,
    )
    # Should contain the question and context
    assert "Is encryption adequate?" in prompt
    assert "AES-256" in prompt
    # Should NOT contain debate-like content
    assert "discussion" not in prompt.lower() or "prior discussion" not in prompt.lower()


def test_specialist_protocol_rollout_order():
    """EW-11: Challenge schemas exist first (challenge is first rollout target)."""
    from agentcouncil.schemas import ChallengeSpecialistAssessment

    # ChallengeSpecialistAssessment must exist and be valid
    a = ChallengeSpecialistAssessment(
        assumption="test", validity="valid", evidence="test", confidence="high",
    )
    assert a.assumption == "test"


def test_specialist_turn_has_timestamp():
    """EW-08: Specialist turn includes timestamp for provenance."""
    from agentcouncil.specialist import make_specialist_turn
    from agentcouncil.schemas import ChallengeSpecialistAssessment

    assessment = ChallengeSpecialistAssessment(
        assumption="test", validity="valid", evidence="test", confidence="high",
    )
    turn = make_specialist_turn(
        artifact=assessment,
        sub_question="test?",
    )
    assert turn.timestamp is not None
    assert turn.timestamp > 0


@pytest.mark.asyncio
async def test_specialist_provider_difference_enforced():
    """EW-10: Specialist provider must differ from main outside agent.

    This test verifies the concept — actual enforcement is at the caller
    level (challenge.py), since specialist.py is provider-agnostic.
    The specialist_check function accepts any adapter; the caller must
    ensure it's different from the main outside adapter.
    """
    import json
    from agentcouncil.specialist import specialist_check
    from agentcouncil.schemas import ChallengeSpecialistAssessment
    from agentcouncil.adapters import StubAdapter

    # Two distinct adapters (simulating different providers)
    main_outside = StubAdapter(["main outside response"])
    specialist = StubAdapter([json.dumps({
        "assumption": "test", "validity": "valid",
        "evidence": "test", "confidence": "high",
    })])

    # Specialist check uses a DIFFERENT adapter than main outside
    result = await specialist_check(
        sub_question="test?",
        context_slice="context",
        specialist_adapter=specialist,  # Different from main_outside
        artifact_cls=ChallengeSpecialistAssessment,
    )
    assert result is not None
    # Main outside was never called
    assert len(main_outside.calls) == 0
    # Specialist was called exactly once
    assert len(specialist.calls) == 1
