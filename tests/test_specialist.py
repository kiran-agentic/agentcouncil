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
