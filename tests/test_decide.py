"""Tests for Decide schema models (DEC-01 through DEC-08, DEC-12)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decide_options():
    """Return two valid DecideOption objects."""
    from agentcouncil.schemas import DecideOption

    return [
        DecideOption(id="opt-a", label="PostgreSQL", description="Relational DB"),
        DecideOption(id="opt-b", label="MongoDB", description="Document store"),
    ]


def _make_option_assessment(**overrides):
    """Helper: build a valid OptionAssessment dict, applying overrides."""
    base = dict(
        option_id="opt-a",
        pros=["Fast reads", "Mature ecosystem"],
        cons=["Complex joins"],
        blocking_risks=[],
        disposition="viable",
        confidence="high",
        source_refs=[],
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# DecideInput tests (DEC-01, DEC-12)
# ---------------------------------------------------------------------------


def test_decide_input_minimal():
    """DecideInput(decision='Which DB?', options=[opt1, opt2]) succeeds."""
    from agentcouncil.schemas import DecideInput

    opts = _make_decide_options()
    di = DecideInput(decision="Which DB?", options=opts)
    assert di.decision == "Which DB?"
    assert len(di.options) == 2


def test_decide_input_one_option_fails():
    """DecideInput with 1 option raises ValidationError (min 2)."""
    from agentcouncil.schemas import DecideInput, DecideOption

    with pytest.raises(ValidationError):
        DecideInput(
            decision="Which DB?",
            options=[DecideOption(id="opt-a", label="PG", description="Relational")],
        )


def test_decide_input_zero_options_fails():
    """DecideInput with 0 options raises ValidationError."""
    from agentcouncil.schemas import DecideInput

    with pytest.raises(ValidationError):
        DecideInput(decision="Which DB?", options=[])


def test_decide_input_no_decision_fails():
    """DecideInput without decision raises ValidationError."""
    from agentcouncil.schemas import DecideInput

    with pytest.raises(ValidationError):
        DecideInput(options=_make_decide_options())


def test_decide_input_rounds_default():
    """DecideInput.rounds defaults to 1 (DEC-12)."""
    from agentcouncil.schemas import DecideInput

    di = DecideInput(decision="Which DB?", options=_make_decide_options())
    assert di.rounds == 1


def test_decide_input_optional_fields():
    """DecideInput accepts optional criteria, constraints, rounds fields."""
    from agentcouncil.schemas import DecideInput

    di = DecideInput(
        decision="Which DB?",
        options=_make_decide_options(),
        criteria="Performance and cost",
        constraints="Must be open source",
        rounds=3,
    )
    assert di.criteria == "Performance and cost"
    assert di.constraints == "Must be open source"
    assert di.rounds == 3


# ---------------------------------------------------------------------------
# DecideOption tests (DEC-01)
# ---------------------------------------------------------------------------


def test_decide_option_valid():
    """DecideOption(id='opt-a', label='PostgreSQL', description='Relational DB') succeeds."""
    from agentcouncil.schemas import DecideOption

    opt = DecideOption(id="opt-a", label="PostgreSQL", description="Relational DB")
    assert opt.id == "opt-a"
    assert opt.label == "PostgreSQL"
    assert opt.description == "Relational DB"


def test_decide_option_missing_fields():
    """DecideOption without id/label/description raises ValidationError."""
    from agentcouncil.schemas import DecideOption

    with pytest.raises(ValidationError):
        DecideOption(id="opt-a", label="PG")  # missing description

    with pytest.raises(ValidationError):
        DecideOption(id="opt-a", description="Relational")  # missing label

    with pytest.raises(ValidationError):
        DecideOption(label="PG", description="Relational")  # missing id


# ---------------------------------------------------------------------------
# OptionAssessment tests (DEC-04, DEC-05)
# ---------------------------------------------------------------------------


def test_option_assessment_valid():
    """OptionAssessment with all fields succeeds."""
    from agentcouncil.schemas import OptionAssessment, SourceRef

    oa = OptionAssessment(
        **_make_option_assessment(
            source_refs=[SourceRef(label="bench", url="https://example.com")]
        )
    )
    assert oa.option_id == "opt-a"
    assert oa.pros == ["Fast reads", "Mature ecosystem"]
    assert oa.cons == ["Complex joins"]
    assert oa.blocking_risks == []
    assert oa.disposition == "viable"
    assert oa.confidence == "high"
    assert len(oa.source_refs) == 1


def test_option_assessment_disposition_values():
    """disposition accepts selected/viable/rejected/insufficient_information only."""
    from agentcouncil.schemas import OptionAssessment

    for disp in ("selected", "viable", "rejected", "insufficient_information"):
        oa = OptionAssessment(**_make_option_assessment(disposition=disp))
        assert oa.disposition == disp

    with pytest.raises(ValidationError):
        OptionAssessment(**_make_option_assessment(disposition="unknown"))


def test_option_assessment_confidence_values():
    """confidence accepts high/medium/low only."""
    from agentcouncil.schemas import OptionAssessment

    for conf in ("high", "medium", "low"):
        oa = OptionAssessment(**_make_option_assessment(confidence=conf))
        assert oa.confidence == conf

    with pytest.raises(ValidationError):
        OptionAssessment(**_make_option_assessment(confidence="uncertain"))


def test_option_assessment_source_refs_default():
    """source_refs defaults to empty list, uses SourceRef type."""
    from agentcouncil.schemas import OptionAssessment

    oa = OptionAssessment(**_make_option_assessment())
    assert oa.source_refs == []


# ---------------------------------------------------------------------------
# DecideArtifact upgrade tests (DEC-02, DEC-03)
# ---------------------------------------------------------------------------


def test_decide_artifact_typed_assessments():
    """option_assessments is list[OptionAssessment] (not list[dict])."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessment = OptionAssessment(**_make_option_assessment(disposition="selected"))
    da = DecideArtifact(
        outcome="decided",
        winner_option_id="opt-a",
        decision_summary="Chose PostgreSQL",
        option_assessments=[assessment],
        next_action="Implement",
    )
    assert len(da.option_assessments) == 1
    assert isinstance(da.option_assessments[0], OptionAssessment)


def test_decide_artifact_json_roundtrip():
    """JSON roundtrip with typed OptionAssessment survives with no field loss."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment, SourceRef

    assessment = OptionAssessment(
        **_make_option_assessment(
            disposition="selected",
            source_refs=[SourceRef(label="bench", path="data/bench.csv")],
        )
    )
    original = DecideArtifact(
        outcome="decided",
        winner_option_id="opt-a",
        decision_summary="Chose PostgreSQL",
        option_assessments=[assessment],
        revisit_triggers=["If latency > 200ms"],
        next_action="Implement",
    )
    json_str = original.model_dump_json()
    restored = DecideArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()
    assert isinstance(restored.option_assessments[0], OptionAssessment)


def test_decided_requires_selected_assessment():
    """outcome='decided' with empty option_assessments is rejected (F-006)."""
    from agentcouncil.schemas import DecideArtifact

    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="decided",
            winner_option_id="opt-a",
            decision_summary="Quick decision",
            option_assessments=[],
            next_action="Go",
        )


# ---------------------------------------------------------------------------
# DEC-06: decided invariant
# ---------------------------------------------------------------------------


def test_decided_one_selected_matching_winner():
    """outcome=decided with exactly one disposition=selected and matching winner_option_id succeeds."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="selected")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="rejected")),
    ]
    da = DecideArtifact(
        outcome="decided",
        winner_option_id="opt-a",
        decision_summary="Chose A",
        option_assessments=assessments,
        next_action="Implement A",
    )
    assert da.outcome == "decided"
    assert da.winner_option_id == "opt-a"


def test_decided_zero_selected_fails():
    """outcome=decided with zero selected raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="viable")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="rejected")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="decided",
            winner_option_id="opt-a",
            decision_summary="Chose A",
            option_assessments=assessments,
            next_action="Implement A",
        )


def test_decided_two_selected_fails():
    """outcome=decided with two selected raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="selected")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="selected")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="decided",
            winner_option_id="opt-a",
            decision_summary="Chose A",
            option_assessments=assessments,
            next_action="Implement A",
        )


def test_decided_winner_mismatch_fails():
    """outcome=decided with winner_option_id not matching the selected option raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="selected")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="rejected")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="decided",
            winner_option_id="opt-b",  # mismatch: opt-a is selected
            decision_summary="Chose B",
            option_assessments=assessments,
            next_action="Implement B",
        )


# ---------------------------------------------------------------------------
# DEC-07: deferred invariant
# ---------------------------------------------------------------------------


def test_deferred_valid():
    """outcome=deferred with zero selected and non-empty defer_reason succeeds."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="viable")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="viable")),
    ]
    da = DecideArtifact(
        outcome="deferred",
        defer_reason="Need performance benchmarks",
        decision_summary="Deferred pending data",
        option_assessments=assessments,
        next_action="Run benchmarks",
    )
    assert da.outcome == "deferred"
    assert da.defer_reason == "Need performance benchmarks"


def test_deferred_with_selected_fails():
    """outcome=deferred with one selected raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="selected")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="viable")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="deferred",
            defer_reason="Need benchmarks",
            decision_summary="Deferred",
            option_assessments=assessments,
            next_action="Run benchmarks",
        )


def test_deferred_empty_reason_fails():
    """outcome=deferred with empty defer_reason raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="viable")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="deferred",
            defer_reason="",
            decision_summary="Deferred",
            option_assessments=assessments,
            next_action="Wait",
        )


# ---------------------------------------------------------------------------
# DEC-08: experiment invariant
# ---------------------------------------------------------------------------


def test_experiment_valid():
    """outcome=experiment with zero selected, at least one viable, non-empty experiment_plan succeeds."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="viable")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="rejected")),
    ]
    da = DecideArtifact(
        outcome="experiment",
        experiment_plan="Run A/B test for 2 weeks",
        decision_summary="Testing both viable options",
        option_assessments=assessments,
        next_action="Set up A/B test",
    )
    assert da.outcome == "experiment"
    assert da.experiment_plan == "Run A/B test for 2 weeks"


def test_experiment_with_selected_fails():
    """outcome=experiment with one selected raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="selected")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="viable")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="experiment",
            experiment_plan="Run A/B test",
            decision_summary="Testing",
            option_assessments=assessments,
            next_action="Test",
        )


def test_experiment_zero_viable_fails():
    """outcome=experiment with zero viable raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="rejected")),
        OptionAssessment(**_make_option_assessment(option_id="opt-b", disposition="rejected")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="experiment",
            experiment_plan="Run A/B test",
            decision_summary="Testing",
            option_assessments=assessments,
            next_action="Test",
        )


def test_experiment_empty_plan_fails():
    """outcome=experiment with empty experiment_plan raises ValidationError."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    assessments = [
        OptionAssessment(**_make_option_assessment(option_id="opt-a", disposition="viable")),
    ]
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="experiment",
            experiment_plan="",
            decision_summary="Testing",
            option_assessments=assessments,
            next_action="Test",
        )


# ---------------------------------------------------------------------------
# decide() function tests (DEC-09 through DEC-12)
# ---------------------------------------------------------------------------

import asyncio
import json

from agentcouncil.adapters import StubAdapter, AdapterError
from agentcouncil.schemas import (
    DeliberationResult,
    DecideArtifact,
    DecideInput,
    DecideOption,
    OptionAssessment,
)


def _make_valid_decide_json():
    """Return a valid DecideArtifact JSON string with typed OptionAssessment objects."""
    return json.dumps({
        "outcome": "decided",
        "winner_option_id": "opt-a",
        "decision_summary": "PostgreSQL chosen for mature ecosystem and reliability",
        "option_assessments": [
            {
                "option_id": "opt-a",
                "pros": ["Mature ecosystem", "ACID compliance"],
                "cons": ["Complex joins at scale"],
                "blocking_risks": [],
                "disposition": "selected",
                "confidence": "high",
                "source_refs": [],
            },
            {
                "option_id": "opt-b",
                "pros": ["Flexible schema", "Horizontal scaling"],
                "cons": ["Eventual consistency", "Less tooling"],
                "blocking_risks": [],
                "disposition": "rejected",
                "confidence": "high",
                "source_refs": [],
            },
        ],
        "defer_reason": None,
        "experiment_plan": None,
        "revisit_triggers": ["If data model becomes heavily nested"],
        "next_action": "Implement PostgreSQL schema",
    })


def _make_decide_input():
    """Build a standard DecideInput for testing."""
    return DecideInput(
        decision="Which database should we use?",
        options=[
            DecideOption(id="opt-a", label="PostgreSQL", description="Relational DB with ACID"),
            DecideOption(id="opt-b", label="MongoDB", description="Document store with flexible schema"),
        ],
        criteria="Performance and reliability",
        constraints="Must be open source",
    )


async def test_decide_returns_envelope():
    """decide() with StubAdapters returns DeliberationResult[DecideArtifact] with outcome, option_assessments, decision_summary."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside decision analysis", valid_json])
    lead = StubAdapter(responses=["Lead decision analysis"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    assert isinstance(result, DeliberationResult)
    assert isinstance(result.artifact, DecideArtifact)
    assert result.artifact.outcome == "decided"
    assert result.artifact.winner_option_id == "opt-a"
    assert len(result.artifact.option_assessments) == 2
    assert isinstance(result.artifact.option_assessments[0], OptionAssessment)


async def test_decide_transcript_populated():
    """result.transcript has input_prompt, outside_initial, lead_initial populated."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside analysis here", valid_json])
    lead = StubAdapter(responses=["Lead analysis here"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    assert result.transcript.input_prompt  # non-empty
    assert result.transcript.outside_initial == "Outside analysis here"
    assert result.transcript.lead_initial == "Lead analysis here"


async def test_decide_default_one_round():
    """decide() with default rounds makes 2 outside calls (initial + synthesis) and 1 lead call (DEC-12)."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside initial", valid_json])
    lead = StubAdapter(responses=["Lead initial"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    # Outside: initial + synthesis = 2 calls
    assert len(outside.calls) == 2
    # Lead: initial only = 1 call
    assert len(lead.calls) == 1
    # No exchanges
    assert len(result.transcript.exchanges) == 0


async def test_decide_input_prompt_factual_only():
    """The input_prompt contains decision, options, criteria, constraints but NOT opinion language (DEC-11)."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    input_prompt = outside.calls[0]
    # Must contain factual content
    assert "Which database should we use?" in input_prompt
    assert "opt-a" in input_prompt
    assert "PostgreSQL" in input_prompt
    assert "opt-b" in input_prompt
    assert "MongoDB" in input_prompt
    assert "Performance and reliability" in input_prompt
    assert "Must be open source" in input_prompt

    # Must NOT contain opinion language (DEC-11)
    for phrase in ["I think", "I prefer", "my recommendation", "I believe", "in my opinion"]:
        assert phrase.lower() not in input_prompt.lower(), f"Found opinion language: '{phrase}'"


async def test_decide_input_prompt_no_preference():
    """The input_prompt has no 'prefer', 'recommend', or 'ranking' language (DEC-11)."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    input_prompt = outside.calls[0]
    for phrase in ["I prefer", "my preference", "I recommend", "my ranking", "I would choose"]:
        assert phrase.lower() not in input_prompt.lower(), f"Found preference language: '{phrase}'"


async def test_decide_synthesis_option_constrained():
    """The synthesis prompt contains 'only' and 'provided options' (DEC-09)."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    synthesis_prompt = outside.calls[1].lower()
    assert "only" in synthesis_prompt
    assert "provided options" in synthesis_prompt or "options listed" in synthesis_prompt or "caller-provided" in synthesis_prompt


async def test_decide_synthesis_no_invent():
    """The synthesis prompt instructs not to invent new options (DEC-09)."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    synthesis_prompt = outside.calls[1].lower()
    assert "do not invent" in synthesis_prompt or "do not propose new" in synthesis_prompt or "do not add new options" in synthesis_prompt


async def test_decide_synthesis_assumptions_tradeoffs():
    """The synthesis prompt instructs to include assumptions, tradeoffs, and confidence for every option (DEC-10)."""
    from agentcouncil.decide import decide

    valid_json = _make_valid_decide_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    synthesis_prompt = outside.calls[1].lower()
    assert "assumptions" in synthesis_prompt
    assert "tradeoffs" in synthesis_prompt
    assert "confidence" in synthesis_prompt


async def test_decide_partial_failure():
    """decide() with failing outside adapter returns partial_failure."""
    from agentcouncil.decide import decide

    class FailingAdapter(StubAdapter):
        def call(self, prompt):
            self.calls.append(prompt)
            raise AdapterError("outside crashed")

    outside = FailingAdapter(responses=[])
    lead = StubAdapter(responses=["Lead should not be called"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    assert result.deliberation_status == "partial_failure"


async def test_decide_validates_input():
    """decide() with empty decision raises ValueError."""
    from agentcouncil.decide import decide

    outside = StubAdapter(responses=["Should not be called"])
    lead = StubAdapter(responses=["Should not be called"])

    di = DecideInput(
        decision="   ",
        options=_make_decide_options(),
    )
    with pytest.raises(ValueError):
        await decide(di, outside, lead)

    # No adapter calls should have been made
    assert len(outside.calls) == 0
    assert len(lead.calls) == 0


# ---------------------------------------------------------------------------
# F-004: Post-parse option validation (DEC-09)
# ---------------------------------------------------------------------------


async def test_decide_rejects_invented_winner():
    """decide() returns unresolved_disagreement when winner_option_id is not in input options (F-004)."""
    from agentcouncil.decide import decide
    from agentcouncil.schemas import ConsensusStatus

    # LLM invents a winner ID not in the input options
    invented_json = json.dumps({
        "outcome": "decided",
        "winner_option_id": "ghost-option",
        "decision_summary": "Ghost wins",
        "option_assessments": [
            {
                "option_id": "ghost-option",
                "pros": ["Invented"], "cons": [],
                "disposition": "selected", "confidence": "high",
            },
        ],
        "next_action": "Go",
    })

    outside = StubAdapter(responses=["Outside analysis", invented_json])
    lead = StubAdapter(responses=["Lead analysis"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    assert result.deliberation_status == ConsensusStatus.unresolved_disagreement


async def test_decide_rejects_invented_assessment_ids():
    """decide() returns unresolved_disagreement when assessment option_ids are not in input (F-004)."""
    from agentcouncil.decide import decide
    from agentcouncil.schemas import ConsensusStatus

    # Valid winner but assessment contains unknown option_id
    bad_json = json.dumps({
        "outcome": "decided",
        "winner_option_id": "opt-a",
        "decision_summary": "A wins",
        "option_assessments": [
            {
                "option_id": "opt-a",
                "pros": ["Good"], "cons": [],
                "disposition": "selected", "confidence": "high",
            },
            {
                "option_id": "opt-unknown",
                "pros": ["?"], "cons": [],
                "disposition": "rejected", "confidence": "low",
            },
        ],
        "next_action": "Go",
    })

    outside = StubAdapter(responses=["Outside analysis", bad_json])
    lead = StubAdapter(responses=["Lead analysis"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    assert result.deliberation_status == ConsensusStatus.unresolved_disagreement


async def test_decide_derive_status_deferred():
    """decide() with deferred outcome returns consensus_with_reservations (F-001)."""
    from agentcouncil.decide import decide
    from agentcouncil.schemas import ConsensusStatus

    deferred_json = json.dumps({
        "outcome": "deferred",
        "decision_summary": "Need more data",
        "defer_reason": "Insufficient benchmarks",
        "option_assessments": [],
        "next_action": "Run benchmarks",
    })

    outside = StubAdapter(responses=["Outside analysis", deferred_json])
    lead = StubAdapter(responses=["Lead analysis"])

    di = _make_decide_input()
    result = await decide(di, outside, lead)

    assert result.deliberation_status == ConsensusStatus.consensus_with_reservations
    assert result.artifact.outcome == "deferred"
