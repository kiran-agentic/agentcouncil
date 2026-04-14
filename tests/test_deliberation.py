from __future__ import annotations

import json

import pytest
from agentcouncil.schemas import ConsensusArtifact, ConsensusStatus


def _make_artifact(**overrides):
    defaults = {
        "recommended_direction": "Use approach A",
        "agreement_points": ["Both agents prefer A"],
        "disagreement_points": [],
        "rejected_alternatives": ["Approach B"],
        "open_risks": ["Untested at scale"],
        "next_action": "Prototype A",
        "status": ConsensusStatus.consensus,
    }
    defaults.update(overrides)
    return ConsensusArtifact(**defaults)


def test_round_transcript_import():
    from agentcouncil.deliberation import RoundTranscript
    assert RoundTranscript is not None


def test_brainstorm_result_import():
    from agentcouncil.deliberation import BrainstormResult
    assert BrainstormResult is not None


def test_round_transcript_still_importable():
    """TN-04: RoundTranscript is deprecated but still importable."""
    from agentcouncil.deliberation import RoundTranscript
    t = RoundTranscript(brief_prompt="the brief")
    assert t.brief_prompt == "the brief"


def test_brainstorm_result_uses_transcript():
    """TN-05: BrainstormResult.transcript is now Transcript type."""
    from agentcouncil.deliberation import BrainstormResult
    from agentcouncil.schemas import Transcript
    artifact = _make_artifact()
    transcript = Transcript(input_prompt="brief text")
    result = BrainstormResult(artifact=artifact, transcript=transcript)
    assert result.artifact.status == "consensus"
    assert result.transcript.input_prompt == "brief text"


def test_brainstorm_result_json_roundtrip():
    from agentcouncil.deliberation import BrainstormResult
    from agentcouncil.schemas import Transcript
    artifact = _make_artifact()
    transcript = Transcript(
        input_prompt="brief",
        outside_initial="outside",
        lead_initial="lead",
        final_output="negotiation",
    )
    original = BrainstormResult(artifact=artifact, transcript=transcript)
    json_str = original.model_dump_json()
    restored = BrainstormResult.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_transcript_input_prompt_required():
    from agentcouncil.schemas import Transcript
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Transcript()  # input_prompt is required


# ---------------------------------------------------------------------------
# Protocol test helpers
# ---------------------------------------------------------------------------


def _valid_brief():
    from agentcouncil.brief import Brief
    return Brief(
        problem_statement="How should we cache session data?",
        background="Current system has no caching layer",
        constraints=["must run on Python 3.12"],
        goals=["reduce DB load by 50%"],
        open_questions=["Redis vs in-memory?"],
    )


def _negotiation_json(**overrides):
    defaults = {
        "recommended_direction": "Use Redis with 15-minute TTL",
        "agreement_points": ["Both agents prefer Redis"],
        "disagreement_points": [],
        "rejected_alternatives": ["In-memory — not shared across processes"],
        "open_risks": ["Redis availability SLA"],
        "next_action": "Prototype Redis integration",
        "status": "consensus",
    }
    defaults.update(overrides)
    return json.dumps(defaults)


class ErrorAdapter:
    """StubAdapter variant that always raises AdapterError on call()."""

    def __init__(self, message: str = "codex timed out") -> None:
        from agentcouncil.adapters import AdapterError
        self._message = message
        self._AdapterError = AdapterError
        self.calls: list[str] = []

    def call(self, prompt: str) -> str:
        self.calls.append(prompt)
        raise self._AdapterError(self._message)

    async def acall(self, prompt: str) -> str:
        return self.call(prompt)


# ---------------------------------------------------------------------------
# Protocol tests (PROTO-01..06, CONS-03, CONS-05)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brainstorm_happy_path_returns_consensus():
    """PROTO-01: brainstorm calls outside twice (round 1 + negotiation), lead once."""
    from agentcouncil.deliberation import brainstorm, BrainstormResult
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert isinstance(result, BrainstormResult)
    assert result.artifact.status == "consensus"
    assert len(outside.calls) == 2   # round 1 + negotiation
    assert len(lead.calls) == 1      # round 2 only


@pytest.mark.asyncio
async def test_outside_agent_sees_only_brief():
    """PROTO-02: outside agent's first call contains only brief.to_prompt(), no lead proposal text."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    await brainstorm(_valid_brief(), outside, lead)

    assert _valid_brief().to_prompt() in outside.calls[0]
    assert "Lead" not in outside.calls[0]  # no lead text in round 1


@pytest.mark.asyncio
async def test_lead_agent_sees_outside_proposal():
    """PROTO-03: lead adapter's call contains both the brief and the outside proposal text."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    await brainstorm(_valid_brief(), outside, lead)

    assert "Outside: use Redis" in lead.calls[0]
    assert _valid_brief().to_prompt() in lead.calls[0]


@pytest.mark.asyncio
async def test_negotiation_prompt_includes_both_proposals():
    """PROTO-04: outside adapter's second call (negotiation) contains both proposals, outside first."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    await brainstorm(_valid_brief(), outside, lead)

    negotiation_prompt = outside.calls[1]
    assert "Outside: use Redis" in negotiation_prompt
    assert "Lead: use Redis with TTL" in negotiation_prompt
    # Outside proposal must appear BEFORE lead proposal
    outside_idx = negotiation_prompt.index("Outside: use Redis")
    lead_idx = negotiation_prompt.index("Lead: use Redis with TTL")
    assert outside_idx < lead_idx


@pytest.mark.asyncio
async def test_context_isolation_outside_never_sees_lead():
    """PROTO-05: outside.calls[0] does NOT contain lead proposal text."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    await brainstorm(_valid_brief(), outside, lead)

    # Round 1 prompt must not contain lead text
    assert "Lead: use Redis with TTL" not in outside.calls[0]


@pytest.mark.asyncio
async def test_unresolved_disagreement_is_valid_result():
    """PROTO-06: non-JSON negotiation output returns unresolved_disagreement, no exception raised."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", "I cannot reach consensus. Incompatible."])
    lead = StubAdapter(["Lead: use in-memory cache"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "unresolved_disagreement"
    # Function did NOT raise


@pytest.mark.asyncio
async def test_outside_agent_error_returns_partial_failure():
    """CONS-03: AdapterError from outside adapter returns partial_failure artifact, does not raise."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = ErrorAdapter("codex timed out")
    lead = StubAdapter(["Lead proposal"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "partial_failure"
    assert result.transcript.outside_initial is None
    assert result.transcript.input_prompt is not None
    assert len(lead.calls) == 0  # lead never called


@pytest.mark.asyncio
async def test_brainstorm_result_includes_transcript():
    """CONS-05: all transcript fields populated in happy path."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.transcript.input_prompt == _valid_brief().to_prompt()
    assert result.transcript.outside_initial == "Outside: use Redis"
    assert result.transcript.lead_initial == "Lead: use Redis with TTL"
    assert result.transcript.final_output is not None


@pytest.mark.asyncio
async def test_lead_agent_error_returns_partial_failure():
    """CONS-03 (lead): AdapterError from lead adapter returns partial_failure artifact."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis"])
    lead = ErrorAdapter("lead timed out")
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "partial_failure"
    assert result.transcript.outside_initial == "Outside: use Redis"
    assert result.transcript.lead_initial is None


# ---------------------------------------------------------------------------
# Deeper behavioral tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_negotiation_error_returns_partial_failure():
    """CONS-03 (negotiation): AdapterError during negotiation round returns partial_failure."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter, AdapterError

    # Outside succeeds round 1 but fails round 3 (negotiation)
    class FailOnSecondCall:
        """Succeeds first call, raises AdapterError on second."""
        def __init__(self):
            self._call_count = 0
            self.calls = []
        def call(self, prompt):
            self.calls.append(prompt)
            self._call_count += 1
            if self._call_count == 1:
                return "Outside proposal"
            raise AdapterError("negotiation timed out")
        async def acall(self, prompt):
            return self.call(prompt)

    outside = FailOnSecondCall()
    lead = StubAdapter(["Lead proposal"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "partial_failure"
    assert result.transcript.outside_initial == "Outside proposal"
    assert result.transcript.lead_initial == "Lead proposal"
    assert result.transcript.final_output is None


@pytest.mark.asyncio
async def test_partial_failure_artifact_has_meaningful_content():
    """Partial failure artifact contains the stage name and error in recommended_direction."""
    from agentcouncil.deliberation import brainstorm

    outside = ErrorAdapter("connection refused")
    lead = ErrorAdapter("should not be called")
    result = await brainstorm(_valid_brief(), outside, lead)

    assert "outside" in result.artifact.recommended_direction.lower()
    assert "connection refused" in result.artifact.recommended_direction
    assert len(result.artifact.open_risks) > 0
    assert result.artifact.next_action  # not empty


@pytest.mark.asyncio
async def test_unresolved_disagreement_artifact_has_meaningful_content():
    """Unresolved disagreement preserves raw negotiation output in transcript."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    raw_negotiation = "I fundamentally disagree with both approaches and cannot synthesize."
    outside = StubAdapter(["Outside: approach A", raw_negotiation])
    lead = StubAdapter(["Lead: approach B"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "unresolved_disagreement"
    assert result.transcript.final_output == raw_negotiation
    assert result.artifact.recommended_direction  # not empty


@pytest.mark.asyncio
async def test_code_fence_wrapped_negotiation_is_parsed():
    """Negotiation JSON wrapped in ```json fences is correctly parsed."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    fenced_json = "```json\n" + _negotiation_json() + "\n```"
    outside = StubAdapter(["Outside: use Redis", fenced_json])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "consensus"


@pytest.mark.asyncio
async def test_consensus_artifact_values_match_negotiation_json():
    """Happy path: artifact field values match what was in the negotiation JSON."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    negotiation = _negotiation_json(
        recommended_direction="Use Redis with 15-minute TTL",
        agreement_points=["Both agents prefer Redis"],
        rejected_alternatives=["In-memory — not shared across processes"],
        status="consensus",
    )
    outside = StubAdapter(["Outside: use Redis", negotiation])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.recommended_direction == "Use Redis with 15-minute TTL"
    assert result.artifact.agreement_points == ["Both agents prefer Redis"]
    assert result.artifact.rejected_alternatives == ["In-memory — not shared across processes"]
    assert result.artifact.status == "consensus"


@pytest.mark.asyncio
async def test_consensus_with_reservations_status():
    """consensus_with_reservations is a valid and correctly parsed status."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    negotiation = _negotiation_json(status="consensus_with_reservations")
    outside = StubAdapter(["Outside: approach A", negotiation])
    lead = StubAdapter(["Lead: approach B"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "consensus_with_reservations"


def test_negotiation_schema_contains_all_status_values():
    """The full model schema includes all 4 status enum values."""
    import json
    from agentcouncil.schemas import ConsensusArtifact
    schema = ConsensusArtifact.model_json_schema()
    schema_str = json.dumps(schema)
    for status in ["consensus", "consensus_with_reservations", "unresolved_disagreement", "partial_failure"]:
        assert status in schema_str, f"Status '{status}' missing from model schema"


@pytest.mark.asyncio
async def test_negotiation_prompt_excludes_partial_failure():
    """The schema sent to the negotiation prompt does NOT include partial_failure."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    await brainstorm(_valid_brief(), outside, lead)

    # The negotiation prompt is outside.calls[1] — it contains the JSON schema
    negotiation_prompt = outside.calls[1]
    # partial_failure should NOT appear in the schema given to the LLM
    assert "partial_failure" not in negotiation_prompt


@pytest.mark.asyncio
async def test_negotiation_returning_partial_failure_normalized_to_unresolved():
    """If the LLM somehow returns partial_failure as status, it's normalized to unresolved_disagreement."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    # Negotiation JSON with partial_failure — should be rejected
    bad_negotiation = _negotiation_json(status="partial_failure")
    outside = StubAdapter(["Outside: approach A", bad_negotiation])
    lead = StubAdapter(["Lead: approach B"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "unresolved_disagreement"
    assert result.transcript.final_output == bad_negotiation


@pytest.mark.asyncio
async def test_brainstorm_never_raises_to_caller():
    """brainstorm() catches all AdapterErrors — never raises to the caller."""
    from agentcouncil.deliberation import brainstorm

    # All adapters fail
    outside = ErrorAdapter("outside dead")
    lead = ErrorAdapter("lead dead")
    result = await brainstorm(_valid_brief(), outside, lead)

    # Should not raise, should return a valid BrainstormResult
    assert result.artifact.status == "partial_failure"
    assert result.transcript.input_prompt is not None


# ---------------------------------------------------------------------------
# Multi-round negotiation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_round_exchanges_recorded():
    """negotiation_rounds=2 produces 2 exchanges (1 pair) before final synthesis."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    # Outside: proposal, exchange response, negotiation JSON = 3 calls
    outside = StubAdapter([
        "Outside: use Redis",
        "Outside exchange: I still prefer Redis after seeing your TTL concern",
        _negotiation_json(),
    ])
    # Lead: proposal, exchange response = 2 calls
    lead = StubAdapter([
        "Lead: use Redis with TTL",
        "Lead exchange: fair point about Redis, but TTL needs to be configurable",
    ])
    result = await brainstorm(_valid_brief(), outside, lead, negotiation_rounds=2)

    assert result.artifact.status == "consensus"
    assert len(result.transcript.exchanges) == 2
    assert result.transcript.exchanges[0].role == "outside"
    assert result.transcript.exchanges[1].role == "lead"
    assert "Redis" in result.transcript.exchanges[0].content
    assert "TTL" in result.transcript.exchanges[1].content
    assert len(outside.calls) == 3  # proposal + exchange + negotiation
    assert len(lead.calls) == 2     # proposal + exchange


@pytest.mark.asyncio
async def test_multi_round_three_rounds():
    """negotiation_rounds=3 produces 4 exchanges (2 pairs) before synthesis."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter([
        "Outside proposal",
        "Outside exchange 1", "Outside exchange 2",
        _negotiation_json(),
    ])
    lead = StubAdapter([
        "Lead proposal",
        "Lead exchange 1", "Lead exchange 2",
    ])
    result = await brainstorm(_valid_brief(), outside, lead, negotiation_rounds=3)

    assert result.artifact.status == "consensus"
    assert len(result.transcript.exchanges) == 4
    assert [e.role for e in result.transcript.exchanges] == [
        "outside", "lead", "outside", "lead",
    ]
    assert len(outside.calls) == 4  # proposal + 2 exchanges + negotiation
    assert len(lead.calls) == 3     # proposal + 2 exchanges


@pytest.mark.asyncio
async def test_default_rounds_no_exchanges():
    """negotiation_rounds=1 (default) produces zero exchanges — original behavior."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter(["Outside: use Redis", _negotiation_json()])
    lead = StubAdapter(["Lead: use Redis with TTL"])
    result = await brainstorm(_valid_brief(), outside, lead)

    assert result.artifact.status == "consensus"
    assert len(result.transcript.exchanges) == 0
    assert len(outside.calls) == 2  # proposal + negotiation
    assert len(lead.calls) == 1     # proposal only


@pytest.mark.asyncio
async def test_exchange_error_returns_partial_failure():
    """AdapterError during an exchange round returns partial_failure with exchanges so far."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter, AdapterError

    class FailOnThirdCall:
        def __init__(self):
            self._count = 0
            self.calls = []
        def call(self, prompt):
            self.calls.append(prompt)
            self._count += 1
            if self._count == 1:
                return "Outside proposal"
            if self._count == 2:
                return "Outside exchange 1"
            raise AdapterError("exchange timed out")
        async def acall(self, prompt):
            return self.call(prompt)

    outside = FailOnThirdCall()
    lead = StubAdapter(["Lead proposal", "Lead exchange 1", "Lead exchange 2"])
    result = await brainstorm(_valid_brief(), outside, lead, negotiation_rounds=3)

    assert result.artifact.status == "partial_failure"
    # First exchange pair completed, second outside exchange failed
    assert len(result.transcript.exchanges) == 2  # outside + lead from round 1
    assert result.transcript.exchanges[0].role == "outside"
    assert result.transcript.exchanges[1].role == "lead"


@pytest.mark.asyncio
async def test_exchange_discussion_forwarded_to_negotiation():
    """The final negotiation prompt contains the exchange discussion."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter([
        "Outside proposal",
        "Outside UNIQUE_EXCHANGE_MARKER response",
        _negotiation_json(),
    ])
    lead = StubAdapter([
        "Lead proposal",
        "Lead UNIQUE_EXCHANGE_MARKER response",
    ])
    result = await brainstorm(_valid_brief(), outside, lead, negotiation_rounds=2)

    # The negotiation prompt (last outside call) should contain exchange content
    negotiation_prompt = outside.calls[-1]
    assert "UNIQUE_EXCHANGE_MARKER" in negotiation_prompt
    assert result.artifact.status == "consensus"


@pytest.mark.asyncio
async def test_exchanges_in_json_roundtrip():
    """BrainstormResult with exchanges survives JSON serialization."""
    from agentcouncil.deliberation import brainstorm, BrainstormResult
    from agentcouncil.adapters import StubAdapter

    outside = StubAdapter([
        "Outside proposal",
        "Outside exchange",
        _negotiation_json(),
    ])
    lead = StubAdapter(["Lead proposal", "Lead exchange"])
    original = await brainstorm(_valid_brief(), outside, lead, negotiation_rounds=2)

    json_str = original.model_dump_json()
    restored = BrainstormResult.model_validate_json(json_str)
    assert len(restored.transcript.exchanges) == 2
    assert restored.transcript.exchanges[0].role == "outside"
    assert restored.transcript.exchanges[1].role == "lead"
    assert restored.model_dump() == original.model_dump()
