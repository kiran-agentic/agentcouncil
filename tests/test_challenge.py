"""Tests for Challenge schema models (CHL-01 through CHL-07, CHL-10, CHL-13)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_failure_mode(**overrides):
    """Helper: build a valid FailureMode dict, applying overrides."""
    base = dict(
        id="FM-001",
        assumption_ref="Users will always have network access",
        description="Offline users cannot sync data",
        severity="high",
        impact="Data loss for mobile users in poor connectivity areas",
        confidence="high",
        disposition="must_harden",
        mitigation=None,
        source_refs=[],
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ChallengeInput tests (CHL-01, CHL-13)
# ---------------------------------------------------------------------------


def test_challenge_input_minimal():
    """ChallengeInput(artifact='some plan') succeeds with defaults (rounds=2)."""
    from agentcouncil.schemas import ChallengeInput

    ci = ChallengeInput(artifact="some plan")
    assert ci.artifact == "some plan"
    assert ci.assumptions == []
    assert ci.success_criteria is None
    assert ci.constraints is None
    assert ci.rounds == 2


def test_challenge_input_full():
    """ChallengeInput with all optional fields set succeeds."""
    from agentcouncil.schemas import ChallengeInput

    ci = ChallengeInput(
        artifact="Deploy microservices on K8s",
        assumptions=["Team has K8s experience", "Budget allows managed cluster"],
        success_criteria="99.9% uptime within 3 months",
        constraints="No vendor lock-in",
        rounds=3,
    )
    assert ci.artifact == "Deploy microservices on K8s"
    assert ci.assumptions == ["Team has K8s experience", "Budget allows managed cluster"]
    assert ci.success_criteria == "99.9% uptime within 3 months"
    assert ci.constraints == "No vendor lock-in"
    assert ci.rounds == 3


def test_challenge_input_artifact_required():
    """ChallengeInput() without artifact raises ValidationError."""
    from agentcouncil.schemas import ChallengeInput

    with pytest.raises(ValidationError):
        ChallengeInput()


def test_challenge_input_rounds_default():
    """ChallengeInput(artifact='x').rounds == 2 (CHL-13)."""
    from agentcouncil.schemas import ChallengeInput

    ci = ChallengeInput(artifact="x")
    assert ci.rounds == 2


# ---------------------------------------------------------------------------
# FailureMode tests (CHL-04, CHL-05)
# ---------------------------------------------------------------------------


def test_failure_mode_model():
    """FailureMode with all fields succeeds."""
    from agentcouncil.schemas import FailureMode, SourceRef

    fm = FailureMode(
        **_make_failure_mode(
            source_refs=[SourceRef(label="design doc", path="docs/arch.md")],
        )
    )
    assert fm.id == "FM-001"
    assert fm.assumption_ref == "Users will always have network access"
    assert fm.description == "Offline users cannot sync data"
    assert fm.severity == "high"
    assert fm.impact == "Data loss for mobile users in poor connectivity areas"
    assert fm.confidence == "high"
    assert fm.disposition == "must_harden"
    assert fm.mitigation is None
    assert len(fm.source_refs) == 1
    assert isinstance(fm.source_refs[0], SourceRef)


def test_failure_mode_severity_values():
    """severity accepts critical/high/medium/low only."""
    from agentcouncil.schemas import FailureMode

    for sev in ("critical", "high", "medium", "low"):
        fm = FailureMode(**_make_failure_mode(severity=sev))
        assert fm.severity == sev

    with pytest.raises(ValidationError):
        FailureMode(**_make_failure_mode(severity="info"))


def test_failure_mode_disposition_values():
    """disposition accepts must_harden/monitor/mitigated/accepted_risk/invalidated only."""
    from agentcouncil.schemas import FailureMode

    for disp in ("must_harden", "monitor", "mitigated", "accepted_risk", "invalidated"):
        fm = FailureMode(**_make_failure_mode(disposition=disp))
        assert fm.disposition == disp

    with pytest.raises(ValidationError):
        FailureMode(**_make_failure_mode(disposition="unknown"))


def test_failure_mode_confidence_values():
    """confidence accepts high/medium/low only."""
    from agentcouncil.schemas import FailureMode

    for conf in ("high", "medium", "low"):
        fm = FailureMode(**_make_failure_mode(confidence=conf))
        assert fm.confidence == conf

    with pytest.raises(ValidationError):
        FailureMode(**_make_failure_mode(confidence="uncertain"))


def test_failure_mode_source_refs_default():
    """source_refs defaults to empty list, uses SourceRef type."""
    from agentcouncil.schemas import FailureMode

    fm = FailureMode(**_make_failure_mode())
    assert fm.source_refs == []


def test_failure_mode_mitigation_optional():
    """mitigation defaults to None."""
    from agentcouncil.schemas import FailureMode

    fm = FailureMode(**_make_failure_mode())
    assert fm.mitigation is None

    fm2 = FailureMode(**_make_failure_mode(mitigation="Add offline queue"))
    assert fm2.mitigation == "Add offline queue"


# ---------------------------------------------------------------------------
# ChallengeArtifact upgrade tests (CHL-02, CHL-06, CHL-07, CHL-10)
# ---------------------------------------------------------------------------


def test_challenge_artifact_typed_failure_modes():
    """failure_modes is list[FailureMode] (not list[dict])."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(**_make_failure_mode(disposition="monitor"))
    ca = ChallengeArtifact(
        readiness="ready",
        summary="Plan is solid",
        failure_modes=[fm],
        next_action="Proceed",
    )
    assert len(ca.failure_modes) == 1
    assert isinstance(ca.failure_modes[0], FailureMode)


def test_challenge_artifact_json_roundtrip():
    """Full ChallengeArtifact with typed FailureMode survives JSON roundtrip."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode, SourceRef

    fm = FailureMode(
        **_make_failure_mode(
            disposition="monitor",
            source_refs=[SourceRef(label="ref", path="a.md")],
            mitigation="Existing retry logic",
        )
    )
    original = ChallengeArtifact(
        readiness="ready",
        summary="Plan reviewed",
        failure_modes=[fm],
        surviving_assumptions=["Users have accounts"],
        break_conditions=["If user base > 10M"],
        residual_risks=["Network latency spikes"],
        next_action="Deploy to staging",
    )
    json_str = original.model_dump_json()
    restored = ChallengeArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()
    assert isinstance(restored.failure_modes[0], FailureMode)
    assert restored.failure_modes[0].mitigation == "Existing retry logic"


def test_challenge_artifact_backward_compat():
    """ChallengeArtifact(readiness='ready', summary='s', failure_modes=[], next_action='a') still works."""
    from agentcouncil.schemas import ChallengeArtifact

    ca = ChallengeArtifact(readiness="ready", summary="s", failure_modes=[], next_action="a")
    assert ca.readiness == "ready"
    assert ca.failure_modes == []
    assert ca.surviving_assumptions == []
    assert ca.break_conditions == []
    assert ca.residual_risks == []


# ---------------------------------------------------------------------------
# Readiness invariant tests (CHL-06, CHL-07, CHL-10)
# ---------------------------------------------------------------------------


def test_ready_no_must_harden():
    """readiness=ready with zero must_harden succeeds (including failure_modes=[])."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    # With a non-must_harden failure mode
    fm = FailureMode(**_make_failure_mode(disposition="monitor"))
    ca = ChallengeArtifact(
        readiness="ready",
        summary="OK",
        failure_modes=[fm],
        next_action="Go",
    )
    assert ca.readiness == "ready"


def test_ready_no_credible_attack():
    """readiness=ready with failure_modes=[] is valid (CHL-10)."""
    from agentcouncil.schemas import ChallengeArtifact

    ca = ChallengeArtifact(
        readiness="ready",
        summary="No credible attack vectors found",
        failure_modes=[],
        next_action="Proceed with confidence",
    )
    assert ca.readiness == "ready"
    assert ca.failure_modes == []


def test_ready_with_must_harden_fails():
    """readiness=ready with one disposition=must_harden raises ValidationError."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(**_make_failure_mode(disposition="must_harden"))
    with pytest.raises(ValidationError):
        ChallengeArtifact(
            readiness="ready",
            summary="OK",
            failure_modes=[fm],
            next_action="Go",
        )


def test_needs_hardening_with_must_harden():
    """readiness=needs_hardening with at least one must_harden succeeds."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(**_make_failure_mode(disposition="must_harden"))
    ca = ChallengeArtifact(
        readiness="needs_hardening",
        summary="Needs work",
        failure_modes=[fm],
        next_action="Harden",
    )
    assert ca.readiness == "needs_hardening"


def test_needs_hardening_without_must_harden_fails():
    """readiness=needs_hardening with zero must_harden raises ValidationError."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(**_make_failure_mode(disposition="monitor"))
    with pytest.raises(ValidationError):
        ChallengeArtifact(
            readiness="needs_hardening",
            summary="Needs work",
            failure_modes=[fm],
            next_action="Harden",
        )


def test_not_ready_with_must_harden():
    """readiness=not_ready with at least one must_harden succeeds."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(**_make_failure_mode(disposition="must_harden"))
    ca = ChallengeArtifact(
        readiness="not_ready",
        summary="Major issues",
        failure_modes=[fm],
        next_action="Redesign",
    )
    assert ca.readiness == "not_ready"


def test_not_ready_without_must_harden_fails():
    """readiness=not_ready with zero must_harden raises ValidationError."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(**_make_failure_mode(disposition="accepted_risk"))
    with pytest.raises(ValidationError):
        ChallengeArtifact(
            readiness="not_ready",
            summary="Major issues",
            failure_modes=[fm],
            next_action="Redesign",
        )


# ---------------------------------------------------------------------------
# challenge() function tests (CHL-08, CHL-09, CHL-11, CHL-12)
# ---------------------------------------------------------------------------

import asyncio
import json

from agentcouncil.adapters import StubAdapter, AdapterError
from agentcouncil.schemas import (
    DeliberationResult,
    ChallengeArtifact,
    ChallengeInput,
    FailureMode,
)


def _make_valid_challenge_json():
    """Return a valid ChallengeArtifact JSON string with typed FailureMode objects."""
    return json.dumps({
        "readiness": "needs_hardening",
        "summary": "Plan has vulnerability in scaling assumptions",
        "failure_modes": [{
            "id": "FM-001",
            "assumption_ref": "Linear scaling",
            "description": "System assumes linear scaling but load tests show exponential",
            "severity": "high",
            "impact": "System crashes at 10x load",
            "confidence": "high",
            "disposition": "must_harden",
            "mitigation": None,
            "source_refs": [],
        }],
        "surviving_assumptions": ["Team has required expertise"],
        "break_conditions": ["If load exceeds 10x baseline"],
        "residual_risks": ["No load testing data beyond 5x"],
        "next_action": "Conduct load testing at 10x scale",
    })


async def test_challenge_returns_envelope():
    """challenge() with StubAdapters returns DeliberationResult[ChallengeArtifact] with readiness, failure_modes, surviving_assumptions."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    # Default rounds=2 means: initial + 1 exchange + synthesis = 3 outside, 2 lead
    outside = StubAdapter(responses=["Outside attack analysis", "Outside exchange attacking defense", valid_json])
    lead = StubAdapter(responses=["Lead defense analysis", "Lead exchange defending"])

    ci = ChallengeInput(artifact="Deploy microservices on K8s")
    result = await challenge(ci, outside, lead)

    assert isinstance(result, DeliberationResult)
    assert isinstance(result.artifact, ChallengeArtifact)
    assert result.artifact.readiness == "needs_hardening"
    assert len(result.artifact.failure_modes) == 1
    assert isinstance(result.artifact.failure_modes[0], FailureMode)
    assert result.artifact.surviving_assumptions == ["Team has required expertise"]


async def test_challenge_transcript_populated():
    """result.transcript has input_prompt, outside_initial, lead_initial populated."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    # Default rounds=2: initial + 1 exchange + synthesis = 3 outside, 2 lead
    outside = StubAdapter(responses=["Outside attack here", "Outside exchange", valid_json])
    lead = StubAdapter(responses=["Lead defense here", "Lead exchange"])

    ci = ChallengeInput(artifact="some plan")
    result = await challenge(ci, outside, lead)

    assert result.transcript.input_prompt  # non-empty
    assert result.transcript.outside_initial == "Outside attack here"
    assert result.transcript.lead_initial == "Lead defense here"


async def test_challenge_default_two_rounds():
    """challenge() with default rounds=2 makes 3 outside calls (initial + 1 exchange + synthesis) and 2 lead calls (initial + 1 exchange)."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    outside = StubAdapter(responses=[
        "Outside attack analysis",
        "Outside exchange response attacking defense",
        valid_json,
    ])
    lead = StubAdapter(responses=[
        "Lead defense analysis",
        "Lead exchange response defending",
    ])

    ci = ChallengeInput(artifact="some plan")
    result = await challenge(ci, outside, lead)

    # Outside: initial + 1 exchange + synthesis = 3 calls
    assert len(outside.calls) == 3
    # Lead: initial + 1 exchange = 2 calls
    assert len(lead.calls) == 2
    # 1 exchange pair = 2 transcript turns
    assert len(result.transcript.exchanges) == 2


async def test_challenge_input_prompt_adversarial():
    """input_prompt contains artifact content, 'attack', 'failure modes', 'assumptions' -- frames as adversarial stress-test."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    outside = StubAdapter(responses=["Outside attack", "Outside exchange", valid_json])
    lead = StubAdapter(responses=["Lead defense", "Lead exchange"])

    ci = ChallengeInput(
        artifact="Deploy microservices on K8s",
        assumptions=["Team has K8s experience"],
        success_criteria="99.9% uptime",
        constraints="No vendor lock-in",
    )
    result = await challenge(ci, outside, lead)

    input_prompt = outside.calls[0]
    assert "Deploy microservices on K8s" in input_prompt
    assert "attack" in input_prompt.lower()
    assert "failure mode" in input_prompt.lower() or "failure modes" in input_prompt.lower()
    assert "assumption" in input_prompt.lower() or "assumptions" in input_prompt.lower()


async def test_challenge_input_prompt_factual_only():
    """input_prompt contains assumptions, success_criteria, constraints but NOT opinion language (CHL-12)."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    outside = StubAdapter(responses=["Outside attack", "Outside exchange", valid_json])
    lead = StubAdapter(responses=["Lead defense", "Lead exchange"])

    ci = ChallengeInput(
        artifact="Deploy microservices on K8s",
        assumptions=["Team has K8s experience"],
        success_criteria="99.9% uptime",
        constraints="No vendor lock-in",
    )
    result = await challenge(ci, outside, lead)

    input_prompt = outside.calls[0]
    assert "Team has K8s experience" in input_prompt
    assert "99.9% uptime" in input_prompt
    assert "No vendor lock-in" in input_prompt

    # Must NOT contain opinion language (CHL-12)
    for phrase in ["I think", "I believe", "my confidence", "I recommend", "in my opinion"]:
        assert phrase.lower() not in input_prompt.lower(), f"Found opinion language: '{phrase}'"


async def test_challenge_input_prompt_no_defense_strategy():
    """input_prompt does NOT contain 'defense', 'defend', 'confident' -- lead's defense strategy excluded (CHL-12)."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    outside = StubAdapter(responses=["Outside attack", "Outside exchange", valid_json])
    lead = StubAdapter(responses=["Lead defense", "Lead exchange"])

    ci = ChallengeInput(artifact="some plan")
    result = await challenge(ci, outside, lead)

    input_prompt = outside.calls[0]
    for phrase in ["defense", "defend", "confident"]:
        assert phrase.lower() not in input_prompt.lower(), f"Found defense language: '{phrase}'"


async def test_challenge_synthesis_adversarial_only():
    """synthesis prompt contains 'attack' and 'do NOT propose repairs' or 'do NOT suggest fixes' (CHL-11)."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    outside = StubAdapter(responses=["Outside attack", "Outside exchange", valid_json])
    lead = StubAdapter(responses=["Lead defense", "Lead exchange"])

    ci = ChallengeInput(artifact="some plan")
    result = await challenge(ci, outside, lead)

    # Synthesis is last outside call
    synthesis_prompt = outside.calls[-1].lower()
    assert "attack" in synthesis_prompt
    assert "do not propose repairs" in synthesis_prompt or "do not suggest fixes" in synthesis_prompt


async def test_challenge_synthesis_defense_arguments():
    """synthesis prompt references 'defense arguments' for exchange context (CHL-09)."""
    from agentcouncil.challenge import challenge

    valid_json = _make_valid_challenge_json()
    outside = StubAdapter(responses=["Outside attack", "Outside exchange", valid_json])
    lead = StubAdapter(responses=["Lead defense", "Lead exchange"])

    ci = ChallengeInput(artifact="some plan")
    result = await challenge(ci, outside, lead)

    synthesis_prompt = outside.calls[-1].lower()
    assert "defense arguments" in synthesis_prompt


async def test_challenge_partial_failure():
    """challenge() with failing outside adapter returns partial_failure."""
    from agentcouncil.challenge import challenge

    class FailingAdapter(StubAdapter):
        def call(self, prompt):
            self.calls.append(prompt)
            raise AdapterError("outside crashed")

    outside = FailingAdapter(responses=[])
    lead = StubAdapter(responses=["Lead should not be called"])

    ci = ChallengeInput(artifact="some plan")
    result = await challenge(ci, outside, lead)

    assert result.deliberation_status == "partial_failure"


async def test_challenge_validates_input():
    """challenge() with empty artifact raises ValueError."""
    from agentcouncil.challenge import challenge

    outside = StubAdapter(responses=["Should not be called"])
    lead = StubAdapter(responses=["Should not be called"])

    ci = ChallengeInput(artifact="   ")
    with pytest.raises(ValueError):
        await challenge(ci, outside, lead)

    # No adapter calls should have been made
    assert len(outside.calls) == 0
    assert len(lead.calls) == 0


# ---------------------------------------------------------------------------
# F-002: Attack vs defense prompt differentiation (CHL-08)
# ---------------------------------------------------------------------------


async def test_challenge_attack_vs_defense_prompts():
    """Outside gets attack prompt, lead gets defense prompt (CHL-08, F-002)."""
    from agentcouncil.challenge import challenge

    # rounds=2 (default): outside needs 3 (initial, exchange, synthesis), lead needs 2 (initial, exchange)
    outside = StubAdapter(responses=[
        "Attack: I found a failure mode",
        "Exchange: pressing on the failure",
        _make_valid_challenge_json(),
    ])
    lead = StubAdapter(responses=[
        "Defense: The plan is robust",
        "Exchange: defending position",
    ])

    ci = ChallengeInput(artifact="Deploy to production with zero downtime")
    await challenge(ci, outside, lead)

    # Outside should receive attack framing
    assert "stress-testing" in outside.calls[0].lower() or "attack" in outside.calls[0].lower()
    assert "find failure modes" in outside.calls[0].lower() or "failure" in outside.calls[0].lower()

    # Lead should receive defense framing
    assert "defending" in lead.calls[0].lower() or "defend" in lead.calls[0].lower()
    assert "strengths" in lead.calls[0].lower() or "why" in lead.calls[0].lower()

    # Both prompts should contain the artifact
    assert "Deploy to production" in outside.calls[0]
    assert "Deploy to production" in lead.calls[0]


async def test_challenge_derive_status_needs_hardening():
    """Challenge with needs_hardening readiness returns consensus_with_reservations (F-001)."""
    from agentcouncil.challenge import challenge
    from agentcouncil.schemas import ConsensusStatus

    synthesis = json.dumps({
        "readiness": "needs_hardening",
        "summary": "Plan has gaps",
        "failure_modes": [{
            "id": "FM-1", "assumption_ref": "A1", "description": "DB fails",
            "severity": "high", "impact": "Outage", "confidence": "high",
            "disposition": "must_harden",
        }],
        "surviving_assumptions": [],
        "break_conditions": ["DB outage"],
        "residual_risks": ["Data loss"],
        "next_action": "Harden DB layer",
    })

    # rounds=2 (default) means 1 exchange pair: outside needs 3 responses, lead needs 2
    outside = StubAdapter(responses=["Attack findings", "Exchange attack", synthesis])
    lead = StubAdapter(responses=["Defense arguments", "Exchange defense"])

    ci = ChallengeInput(artifact="Deploy plan")
    result = await challenge(ci, outside, lead)

    assert result.deliberation_status == ConsensusStatus.consensus_with_reservations
    assert result.artifact.readiness == "needs_hardening"
