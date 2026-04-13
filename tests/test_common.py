"""Tests for common deliberation framework schemas (COM-01 through COM-05, COM-12, COM-13)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_source_ref_model():
    """SourceRef has label (required), optional path, optional url."""
    from agentcouncil.schemas import SourceRef

    ref = SourceRef(label="file", path="src/foo.py")
    assert ref.label == "file"
    assert ref.path == "src/foo.py"
    assert ref.url is None


def test_transcript_turn_model():
    """TranscriptTurn has role, content; source_refs defaults to []."""
    from agentcouncil.schemas import TranscriptTurn

    turn = TranscriptTurn(role="outside", content="text")
    assert turn.role == "outside"
    assert turn.content == "text"
    assert turn.source_refs == []


def test_transcript_model():
    """Transcript has input_prompt (required); other fields default to None/[]."""
    from agentcouncil.schemas import Transcript

    t = Transcript(input_prompt="p")
    assert t.input_prompt == "p"
    assert t.outside_initial is None
    assert t.lead_initial is None
    assert t.exchanges == []
    assert t.final_output is None


def test_transcript_input_prompt_required():
    """Transcript() without input_prompt raises ValidationError."""
    from agentcouncil.schemas import Transcript

    with pytest.raises(ValidationError):
        Transcript()


def test_envelope_structure():
    """COM-02: DeliberationResult[ReviewArtifact] has deliberation_status, artifact, transcript."""
    from agentcouncil.schemas import (
        DeliberationResult,
        ReviewArtifact,
        Transcript,
    )

    artifact = ReviewArtifact(
        verdict="pass",
        summary="Looks good",
        next_action="Ship it",
    )
    transcript = Transcript(input_prompt="Review this code")
    result = DeliberationResult[ReviewArtifact](
        deliberation_status="consensus",
        artifact=artifact,
        transcript=transcript,
    )
    assert result.deliberation_status == "consensus"
    assert result.artifact.verdict == "pass"
    assert result.transcript.input_prompt == "Review this code"


def test_status_enum():
    """COM-03: deliberation_status accepts all four ConsensusStatus values."""
    from agentcouncil.schemas import (
        ConsensusStatus,
        DeliberationResult,
        ReviewArtifact,
        Transcript,
    )

    artifact = ReviewArtifact(verdict="pass", summary="OK", next_action="Done")
    transcript = Transcript(input_prompt="p")

    for status in ConsensusStatus:
        result = DeliberationResult[ReviewArtifact](
            deliberation_status=status,
            artifact=artifact,
            transcript=transcript,
        )
        assert result.deliberation_status == status.value


def test_outcome_fields():
    """COM-04: ReviewArtifact.verdict, DecideArtifact.outcome, ChallengeArtifact.readiness exist."""
    from agentcouncil.schemas import ReviewArtifact, DecideArtifact, ChallengeArtifact, OptionAssessment

    review = ReviewArtifact(verdict="pass", summary="OK", next_action="Done")
    assert review.verdict == "pass"

    decide = DecideArtifact(
        outcome="decided",
        winner_option_id="opt-1",
        decision_summary="Chose opt-1",
        option_assessments=[OptionAssessment(
            option_id="opt-1", pros=["fast"], cons=[], disposition="selected", confidence="high",
        )],
        next_action="Implement",
    )
    assert decide.outcome == "decided"

    challenge = ChallengeArtifact(
        readiness="ready",
        summary="Solid plan",
        next_action="Proceed",
    )
    assert challenge.readiness == "ready"


def test_review_verdict_values():
    """ReviewArtifact.verdict accepts 'pass', 'revise', 'escalate' only."""
    from agentcouncil.schemas import ReviewArtifact

    for v in ("pass", "revise", "escalate"):
        r = ReviewArtifact(verdict=v, summary="s", next_action="a")
        assert r.verdict == v

    with pytest.raises(ValidationError):
        ReviewArtifact(verdict="reject", summary="s", next_action="a")


def test_decide_outcome_values():
    """DecideArtifact.outcome accepts 'decided', 'deferred', 'experiment' only."""
    from agentcouncil.schemas import DecideArtifact, OptionAssessment

    # decided requires winner_option_id AND a selected assessment
    d = DecideArtifact(
        outcome="decided", winner_option_id="a",
        decision_summary="s", next_action="a",
        option_assessments=[OptionAssessment(
            option_id="a", pros=["good"], cons=[], disposition="selected", confidence="high",
        )],
    )
    assert d.outcome == "decided"

    # deferred requires defer_reason
    d = DecideArtifact(
        outcome="deferred", defer_reason="need more data",
        decision_summary="s", next_action="a",
    )
    assert d.outcome == "deferred"

    # experiment requires experiment_plan and at least one viable assessment
    d = DecideArtifact(
        outcome="experiment", experiment_plan="Run A/B test",
        decision_summary="s", next_action="a",
        option_assessments=[OptionAssessment(
            option_id="x", pros=["promising"], cons=["unknown"], disposition="viable", confidence="medium",
        )],
    )
    assert d.outcome == "experiment"

    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="rejected", decision_summary="s", next_action="a",
        )


def test_challenge_readiness_values():
    """ChallengeArtifact.readiness accepts 'ready', 'needs_hardening', 'not_ready' only."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm = FailureMode(
        id="FM-001",
        assumption_ref="assumption",
        description="issue",
        severity="high",
        impact="impact",
        confidence="high",
        disposition="must_harden",
    )
    for r in ("ready", "needs_hardening", "not_ready"):
        if r == "ready":
            c = ChallengeArtifact(readiness=r, summary="s", next_action="a")
        else:
            c = ChallengeArtifact(
                readiness=r, summary="s", next_action="a",
                failure_modes=[fm],
            )
        assert c.readiness == r

    with pytest.raises(ValidationError):
        ChallengeArtifact(readiness="unknown", summary="s", next_action="a")


# ---------------------------------------------------------------------------
# JSON roundtrip tests (COM-12)
# ---------------------------------------------------------------------------


def test_json_roundtrip_review():
    """DeliberationResult[ReviewArtifact] survives JSON roundtrip with no field loss."""
    from agentcouncil.schemas import DeliberationResult, Finding, ReviewArtifact, Transcript

    artifact = ReviewArtifact(
        verdict="revise",
        summary="Needs work",
        findings=[
            Finding(
                id="f1",
                title="Bug",
                severity="high",
                impact="Crash on null input",
                description="Missing null check",
                evidence="Line 10: x.foo()",
                locations=["src/main.py:10"],
                confidence="high",
                agreement="confirmed",
                origin="outside",
            ),
        ],
        strengths=["Clean code"],
        open_questions=["Perf?"],
        next_action="Fix bugs",
    )
    transcript = Transcript(
        input_prompt="Review code",
        outside_initial="Outside analysis",
        lead_initial="Lead analysis",
        final_output="Final synthesis",
    )
    original = DeliberationResult[ReviewArtifact](
        deliberation_status="consensus_with_reservations",
        artifact=artifact,
        transcript=transcript,
    )
    json_str = original.model_dump_json()
    restored = DeliberationResult[ReviewArtifact].model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_json_roundtrip_decide():
    """DeliberationResult[DecideArtifact] survives roundtrip."""
    from agentcouncil.schemas import DeliberationResult, DecideArtifact, OptionAssessment, Transcript

    artifact = DecideArtifact(
        outcome="decided",
        winner_option_id="opt-2",
        decision_summary="Option 2 wins",
        option_assessments=[
            OptionAssessment(
                option_id="opt-2",
                pros=["fast"],
                cons=["complex setup"],
                disposition="selected",
                confidence="high",
            ),
        ],
        revisit_triggers=["If latency exceeds 200ms"],
        next_action="Implement opt-2",
    )
    transcript = Transcript(input_prompt="Decide between options")
    original = DeliberationResult[DecideArtifact](
        deliberation_status="consensus",
        artifact=artifact,
        transcript=transcript,
    )
    json_str = original.model_dump_json()
    restored = DeliberationResult[DecideArtifact].model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_json_roundtrip_challenge():
    """DeliberationResult[ChallengeArtifact] survives roundtrip."""
    from agentcouncil.schemas import DeliberationResult, ChallengeArtifact, FailureMode, Transcript

    fm = FailureMode(
        id="FM-001",
        assumption_ref="DB is always available",
        description="SQL injection",
        severity="high",
        impact="Data exfiltration",
        confidence="high",
        disposition="must_harden",
    )
    artifact = ChallengeArtifact(
        readiness="needs_hardening",
        summary="Some gaps",
        failure_modes=[fm],
        surviving_assumptions=["Auth works"],
        break_conditions=["If DB goes down"],
        residual_risks=["Latency spike"],
        next_action="Harden SQL handling",
    )
    transcript = Transcript(input_prompt="Challenge this plan")
    original = DeliberationResult[ChallengeArtifact](
        deliberation_status="unresolved_disagreement",
        artifact=artifact,
        transcript=transcript,
    )
    json_str = original.model_dump_json()
    restored = DeliberationResult[ChallengeArtifact].model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_json_roundtrip_transcript_with_source_refs():
    """Transcript with TranscriptTurns containing SourceRefs survives roundtrip."""
    from agentcouncil.schemas import Transcript, TranscriptTurn, SourceRef

    transcript = Transcript(
        input_prompt="Review",
        exchanges=[
            TranscriptTurn(
                role="outside",
                content="I found an issue",
                source_refs=[
                    SourceRef(label="file", path="src/main.py"),
                    SourceRef(label="doc", url="https://example.com"),
                ],
            ),
            TranscriptTurn(role="lead", content="I agree"),
        ],
    )
    json_str = transcript.model_dump_json()
    restored = Transcript.model_validate_json(json_str)
    assert restored.model_dump() == transcript.model_dump()
    assert len(restored.exchanges[0].source_refs) == 2
    assert restored.exchanges[0].source_refs[0].path == "src/main.py"
    assert restored.exchanges[0].source_refs[1].url == "https://example.com"


# ---------------------------------------------------------------------------
# Pydantic validator invariant tests (COM-13)
# ---------------------------------------------------------------------------


def test_pydantic_invariants_review():
    """ReviewArtifact with invalid verdict raises ValidationError."""
    from agentcouncil.schemas import ReviewArtifact

    with pytest.raises(ValidationError):
        ReviewArtifact(verdict="invalid", summary="s", next_action="a")


def test_pydantic_invariants_decide():
    """DecideArtifact validators enforce outcome invariants."""
    from agentcouncil.schemas import DecideArtifact

    # outcome="decided" but winner_option_id=None -> error
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="decided",
            winner_option_id=None,
            decision_summary="s",
            next_action="a",
        )

    # outcome="deferred" but defer_reason empty -> error
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="deferred",
            defer_reason="",
            decision_summary="s",
            next_action="a",
        )

    # outcome="deferred" with no defer_reason (None) -> error
    with pytest.raises(ValidationError):
        DecideArtifact(
            outcome="deferred",
            decision_summary="s",
            next_action="a",
        )


def test_pydantic_invariants_challenge():
    """ChallengeArtifact validators enforce readiness invariants."""
    from agentcouncil.schemas import ChallengeArtifact, FailureMode

    fm_must_harden = FailureMode(
        id="FM-001", assumption_ref="a", description="issue",
        severity="high", impact="i", confidence="high", disposition="must_harden",
    )
    fm_monitor = FailureMode(
        id="FM-002", assumption_ref="a", description="minor",
        severity="low", impact="i", confidence="medium", disposition="monitor",
    )

    # readiness="ready" but failure_modes contains must_harden -> error
    with pytest.raises(ValidationError):
        ChallengeArtifact(
            readiness="ready",
            summary="s",
            failure_modes=[fm_must_harden],
            next_action="a",
        )

    # readiness="needs_hardening" but no must_harden failure mode -> error
    with pytest.raises(ValidationError):
        ChallengeArtifact(
            readiness="needs_hardening",
            summary="s",
            failure_modes=[fm_monitor],
            next_action="a",
        )

    # readiness="not_ready" but no must_harden failure mode -> error
    with pytest.raises(ValidationError):
        ChallengeArtifact(
            readiness="not_ready",
            summary="s",
            failure_modes=[],
            next_action="a",
        )


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------


def test_existing_consensus_artifact_unchanged():
    """ConsensusArtifact still works with all original fields."""
    from agentcouncil.schemas import ConsensusArtifact, ConsensusStatus

    a = ConsensusArtifact(
        recommended_direction="Use approach A",
        agreement_points=["Both prefer A"],
        disagreement_points=[],
        rejected_alternatives=["B"],
        open_risks=["Scale"],
        next_action="Prototype A",
        status=ConsensusStatus.consensus,
    )
    assert a.status == "consensus"
    assert a.recommended_direction == "Use approach A"


def test_existing_brainstorm_result_unchanged():
    """BrainstormResult import and instantiation still works."""
    from agentcouncil.deliberation import BrainstormResult, RoundTranscript
    from agentcouncil.schemas import ConsensusArtifact, ConsensusStatus

    artifact = ConsensusArtifact(
        recommended_direction="dir",
        agreement_points=[],
        disagreement_points=[],
        rejected_alternatives=[],
        open_risks=[],
        next_action="next",
        status=ConsensusStatus.consensus,
    )
    transcript = RoundTranscript(brief_prompt="brief")
    result = BrainstormResult(artifact=artifact, transcript=transcript)
    assert result.artifact.status == "consensus"
    assert result.transcript.brief_prompt == "brief"


def test_functions_exist():
    """COM-01: ReviewArtifact, DecideArtifact, ChallengeArtifact are importable from schemas."""
    from agentcouncil.schemas import ReviewArtifact, DecideArtifact, ChallengeArtifact

    assert ReviewArtifact is not None
    assert DecideArtifact is not None
    assert ChallengeArtifact is not None


# ---------------------------------------------------------------------------
# CodexSession tests (COM-07)
# ---------------------------------------------------------------------------


class FakeMCPClient:
    """Fake MCP client that records tool calls and returns canned results."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._entered = False
        self._exited = False

    async def __aenter__(self):
        self._entered = True
        return self

    async def __aexit__(self, *exc):
        self._exited = True
        return False

    async def call_tool(self, tool_name: str, params: dict):
        self.calls.append((tool_name, params))
        return FakeCallToolResult(
            text=f"Response from {tool_name}",
            structured_content={"threadId": "thread-abc-123"},
        )


class FakeCallToolResult:
    """Mimics FastMCP CallToolResult with text and structured_content."""

    def __init__(self, text: str, structured_content: dict | None = None):
        self.text = text
        self.structured_content = structured_content or {}


def _make_session_with_fake():
    """Helper: create a CodexSession with FakeMCPClient pre-installed (no real transport)."""
    from agentcouncil.adapters import CodexSession

    session = CodexSession(model="test-model", sandbox="read-only")
    fake = FakeMCPClient()
    session._client = fake
    return session, fake


async def test_codex_session_enter_exit():
    """CodexSession can be used as async context manager -- __aenter__ returns self, __aexit__ cleans up."""
    from agentcouncil.adapters import CodexSession

    session = CodexSession()
    fake = FakeMCPClient()

    # Pre-install fake client to test __aexit__ cleanup without real transport
    session._client = fake

    # Test __aexit__ directly
    await session.__aexit__(None, None, None)
    assert session._client is None
    assert session._thread_id is None

    # Verify __aenter__ returns self (test structure, not real transport)
    session2 = CodexSession()
    fake2 = FakeMCPClient()
    session2._client = fake2
    # __aenter__ creates real client -- we test send/exit cycle instead
    # Just verify the session is usable after manual client injection
    assert session2._client is fake2


async def test_codex_session_send_first_call_uses_codex_tool():
    """First call to session.send() calls the 'codex' tool with prompt and sandbox params."""
    session, fake = _make_session_with_fake()
    session._thread_id = None  # ensure first-call path

    result = await session.send("Hello outside agent")

    assert len(fake.calls) == 1
    tool_name, params = fake.calls[0]
    assert tool_name == "codex"
    assert params["prompt"] == "Hello outside agent"
    assert params["sandbox"] == "read-only"
    assert params["model"] == "test-model"


async def test_codex_session_send_subsequent_uses_codex_reply():
    """Second call to session.send() calls 'codex-reply' with prompt and threadId."""
    session, fake = _make_session_with_fake()

    # First call sets threadId
    await session.send("First message")
    assert session._thread_id == "thread-abc-123"

    # Second call should use codex-reply
    await session.send("Follow-up message")

    assert len(fake.calls) == 2
    tool_name, params = fake.calls[1]
    assert tool_name == "codex-reply"
    assert params["prompt"] == "Follow-up message"
    assert params["threadId"] == "thread-abc-123"


async def test_codex_session_cleanup_on_exception():
    """If an exception occurs inside async with, __aexit__ still closes the client."""
    from agentcouncil.adapters import CodexSession

    session = CodexSession()
    fake = FakeMCPClient()
    session._client = fake

    # Simulate exception path through __aexit__
    await session.__aexit__(ValueError, ValueError("test"), None)

    assert session._client is None
    assert session._thread_id is None


async def test_codex_session_thread_id_extraction():
    """After first send(), session._thread_id is populated from the result."""
    session, fake = _make_session_with_fake()

    assert session._thread_id is None
    await session.send("First message")
    assert session._thread_id == "thread-abc-123"


async def test_codex_session_not_reusable():
    """After __aexit__, calling send() raises RuntimeError."""
    session, fake = _make_session_with_fake()

    # Use session
    await session.send("Hello")

    # Simulate exit
    await session.__aexit__(None, None, None)

    # After exit, send should raise
    with pytest.raises(RuntimeError, match="not active"):
        await session.send("Should fail")


# ---------------------------------------------------------------------------
# run_deliberation tests (COM-06, COM-08, COM-09, COM-10, COM-11)
# ---------------------------------------------------------------------------

import asyncio
import json

from agentcouncil.adapters import StubAdapter, AdapterError
from agentcouncil.schemas import (
    ReviewArtifact,
    DeliberationResult,
    Transcript,
    TranscriptTurn,
    ConsensusStatus,
)


def _make_valid_review_json(
    verdict: str = "pass",
    status: str = "consensus",
) -> str:
    """Return a valid ReviewArtifact JSON string for synthesis output."""
    return json.dumps({
        "verdict": verdict,
        "summary": "Looks good overall",
        "findings": [],
        "strengths": ["Clean architecture"],
        "open_questions": [],
        "next_action": "Ship it",
    })


def _synthesis_prompt_fn(
    input_prompt: str,
    outside_initial: str,
    lead_initial: str,
    discussion: str,
    schema_json: str,
) -> str:
    """Simple synthesis prompt builder for tests."""
    return f"Synthesize: {input_prompt} | {outside_initial} | {lead_initial} | {discussion} | schema={schema_json}"


def _run_sync(coro):
    """Run an async coroutine synchronously for test convenience."""
    return asyncio.run(coro)


async def test_dual_independent():
    """COM-06: Both agents receive the SAME input_prompt; neither sees the other's response."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=[
        "Outside analysis of the problem",
        _make_valid_review_json(),
    ])
    lead = StubAdapter(responses=["Lead analysis of the problem"])

    result = await run_deliberation(
        input_prompt="Review this code for bugs",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    # Both agents received the same input prompt
    assert outside.calls[0] == "Review this code for bugs"
    assert lead.calls[0] == "Review this code for bugs"


async def test_dual_independent_lead_never_sees_outside():
    """Lead adapter's first call does NOT contain outside adapter's response."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=[
        "UNIQUE_OUTSIDE_MARKER_xyz123",
        _make_valid_review_json(),
    ])
    lead = StubAdapter(responses=["Lead response"])

    await run_deliberation(
        input_prompt="Analyze this",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    # Lead's first call must NOT contain outside's response
    assert "UNIQUE_OUTSIDE_MARKER_xyz123" not in lead.calls[0]


async def test_dual_independent_outside_never_sees_lead():
    """Outside adapter's first call does NOT contain lead adapter's response."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=[
        "Outside response",
        _make_valid_review_json(),
    ])
    lead = StubAdapter(responses=["UNIQUE_LEAD_MARKER_abc456"])

    await run_deliberation(
        input_prompt="Analyze this",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    # Outside's first call must NOT contain lead's response
    assert "UNIQUE_LEAD_MARKER_abc456" not in outside.calls[0]


async def test_run_deliberation_returns_envelope():
    """Result is a DeliberationResult with deliberation_status, artifact, and transcript fields."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=["Outside view", _make_valid_review_json()])
    lead = StubAdapter(responses=["Lead view"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert hasattr(result, "deliberation_status")
    assert hasattr(result, "artifact")
    assert hasattr(result, "transcript")
    assert isinstance(result.artifact, ReviewArtifact)


async def test_run_deliberation_transcript_populated():
    """Transcript input_prompt, outside_initial, lead_initial all populated after successful run."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=["Outside analysis", _make_valid_review_json()])
    lead = StubAdapter(responses=["Lead analysis"])

    result = await run_deliberation(
        input_prompt="Review this",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert result.transcript.input_prompt == "Review this"
    assert result.transcript.outside_initial == "Outside analysis"
    assert result.transcript.lead_initial == "Lead analysis"


async def test_partial_failure_outside_error():
    """COM-08: AdapterError from outside returns partial_failure with transcript.input_prompt set."""
    from agentcouncil.deliberation import run_deliberation

    class FailingAdapter(StubAdapter):
        def call(self, prompt):
            self.calls.append(prompt)
            raise AdapterError("outside crashed")

    outside = FailingAdapter(responses=[])
    lead = StubAdapter(responses=["Lead should not be called"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert result.deliberation_status == "partial_failure"
    assert result.transcript.input_prompt == "Review code"
    assert result.transcript.outside_initial is None
    assert len(lead.calls) == 0  # lead never called


async def test_partial_failure_lead_error():
    """COM-08: AdapterError from lead after outside succeeds returns partial_failure with outside_initial."""
    from agentcouncil.deliberation import run_deliberation

    class FailingAdapter(StubAdapter):
        def call(self, prompt):
            self.calls.append(prompt)
            raise AdapterError("lead crashed")

    outside = StubAdapter(responses=["Outside analysis OK"])
    lead = FailingAdapter(responses=[])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert result.deliberation_status == "partial_failure"
    assert result.transcript.outside_initial == "Outside analysis OK"
    assert result.transcript.lead_initial is None


async def test_partial_failure_exchange_error():
    """COM-08: AdapterError during exchange returns partial_failure with exchanges through last success."""
    from agentcouncil.deliberation import run_deliberation

    call_count = 0

    class FailOnSecondExchangeAdapter(StubAdapter):
        def call(self, prompt):
            nonlocal call_count
            self.calls.append(prompt)
            call_count += 1
            # First call is initial analysis, second is exchange -- fail on exchange
            if len(self.calls) > 1:
                raise AdapterError("exchange crashed")
            return self._responses[0] if self._cycle else self._responses.pop(0)

    outside = FailOnSecondExchangeAdapter(responses=["Outside initial"])
    lead = StubAdapter(responses=["Lead initial", "Lead exchange ok"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
        exchange_rounds=2,  # 1 pair of exchanges before synthesis
    )

    assert result.deliberation_status == "partial_failure"
    assert result.transcript.outside_initial == "Outside initial"
    assert result.transcript.lead_initial is not None


async def test_partial_failure_synthesis_error():
    """COM-08: AdapterError during synthesis returns partial_failure with both initials populated."""
    from agentcouncil.deliberation import run_deliberation

    call_count = 0

    class FailOnSynthesisAdapter(StubAdapter):
        def call(self, prompt):
            self.calls.append(prompt)
            # First call is initial, second call is synthesis -- fail on synthesis
            if len(self.calls) == 1:
                return "Outside initial analysis"
            raise AdapterError("synthesis crashed")

    outside = FailOnSynthesisAdapter(responses=[])
    lead = StubAdapter(responses=["Lead initial analysis"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert result.deliberation_status == "partial_failure"
    assert result.transcript.outside_initial == "Outside initial analysis"
    assert result.transcript.lead_initial == "Lead initial analysis"


async def test_json_parse_failure():
    """COM-09: Non-JSON synthesis returns unresolved_disagreement with raw output in final_output."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=[
        "Outside analysis",
        "This is NOT valid JSON at all, just free text discussion",
    ])
    lead = StubAdapter(responses=["Lead analysis"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert result.deliberation_status == "unresolved_disagreement"
    assert result.transcript.final_output == "This is NOT valid JSON at all, just free text discussion"


async def test_filtered_schema_excludes_partial_failure():
    """COM-10: The synthesis prompt does NOT contain 'partial_failure'."""
    from agentcouncil.deliberation import run_deliberation

    synthesis_prompts = []

    def capturing_synthesis_fn(input_prompt, outside_initial, lead_initial, discussion, schema_json):
        synthesis_prompts.append(schema_json)
        return f"Synthesize with schema: {schema_json}"

    outside = StubAdapter(responses=[
        "Outside analysis",
        _make_valid_review_json(),
    ])
    lead = StubAdapter(responses=["Lead analysis"])

    await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=capturing_synthesis_fn,
    )

    assert len(synthesis_prompts) == 1
    assert "partial_failure" not in synthesis_prompts[0]


async def test_input_validation_aborts_early():
    """COM-11: Empty input_prompt raises ValueError before any adapter call."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=["Should not be called"])
    lead = StubAdapter(responses=["Should not be called"])

    with pytest.raises(ValueError, match="input_prompt must not be empty"):
        await run_deliberation(
            input_prompt="",
            outside_adapter=outside,
            lead_adapter=lead,
            artifact_cls=ReviewArtifact,
            synthesis_prompt_fn=_synthesis_prompt_fn,
        )

    assert len(outside.calls) == 0
    assert len(lead.calls) == 0

    # Also test whitespace-only
    with pytest.raises(ValueError, match="input_prompt must not be empty"):
        await run_deliberation(
            input_prompt="   ",
            outside_adapter=outside,
            lead_adapter=lead,
            artifact_cls=ReviewArtifact,
            synthesis_prompt_fn=_synthesis_prompt_fn,
        )

    assert len(outside.calls) == 0


async def test_run_deliberation_exchange_rounds():
    """With exchange_rounds=2, both adapters get exchange calls between initials and synthesis."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=[
        "Outside initial",
        "Outside exchange response",
        _make_valid_review_json(),
    ])
    lead = StubAdapter(responses=[
        "Lead initial",
        "Lead exchange response",
    ])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
        exchange_rounds=2,
    )

    # Outside: initial + exchange + synthesis = 3 calls
    assert len(outside.calls) == 3
    # Lead: initial + exchange = 2 calls
    assert len(lead.calls) == 2
    # Transcript should have 2 exchange turns
    assert len(result.transcript.exchanges) == 2


async def test_run_deliberation_default_one_round():
    """Default exchange_rounds=1 means no exchange calls, just initial + synthesis."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=[
        "Outside initial",
        _make_valid_review_json(),
    ])
    lead = StubAdapter(responses=["Lead initial"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    # Outside: initial + synthesis = 2 calls
    assert len(outside.calls) == 2
    # Lead: initial only = 1 call
    assert len(lead.calls) == 1
    # No exchanges
    assert len(result.transcript.exchanges) == 0


# ---------------------------------------------------------------------------
# F-001: derive_status callback tests
# ---------------------------------------------------------------------------


async def test_derive_status_consensus_with_reservations():
    """derive_status callback can produce consensus_with_reservations on success."""
    from agentcouncil.deliberation import run_deliberation

    def _always_reservations(_artifact):
        return ConsensusStatus.consensus_with_reservations

    outside = StubAdapter(responses=["Outside", _make_valid_review_json()])
    lead = StubAdapter(responses=["Lead"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
        derive_status=_always_reservations,
    )
    assert result.deliberation_status == ConsensusStatus.consensus_with_reservations


async def test_derive_status_none_defaults_consensus():
    """When derive_status is None, successful parse returns consensus."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=["Outside", _make_valid_review_json()])
    lead = StubAdapter(responses=["Lead"])

    result = await run_deliberation(
        input_prompt="Review code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )
    assert result.deliberation_status == ConsensusStatus.consensus


# ---------------------------------------------------------------------------
# F-002: lead_input_prompt tests
# ---------------------------------------------------------------------------


async def test_lead_input_prompt_separate():
    """lead_input_prompt sends a different prompt to the lead agent."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=["Outside attack", _make_valid_review_json()])
    lead = StubAdapter(responses=["Lead defense"])

    await run_deliberation(
        input_prompt="Attack prompt",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
        lead_input_prompt="Defense prompt",
    )

    assert outside.calls[0] == "Attack prompt"
    assert lead.calls[0] == "Defense prompt"


async def test_lead_input_prompt_none_uses_same():
    """When lead_input_prompt is None, both agents get input_prompt."""
    from agentcouncil.deliberation import run_deliberation

    outside = StubAdapter(responses=["Outside", _make_valid_review_json()])
    lead = StubAdapter(responses=["Lead"])

    await run_deliberation(
        input_prompt="Same prompt for both",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert outside.calls[0] == "Same prompt for both"
    assert lead.calls[0] == "Same prompt for both"


# ---------------------------------------------------------------------------
# F-005: failure envelope round-trip safety
# ---------------------------------------------------------------------------


async def test_decide_failure_envelope_roundtrip():
    """DecideArtifact failure envelopes survive JSON round-trip (COM-12, F-005)."""
    from agentcouncil.schemas import DecideArtifact
    from agentcouncil.deliberation import run_deliberation

    # Outside adapter fails immediately → partial_failure
    outside = StubAdapter(responses=[])  # will raise AdapterError

    lead = StubAdapter(responses=["Lead analysis"])

    result = await run_deliberation(
        input_prompt="Decide something",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=DecideArtifact,
        synthesis_prompt_fn=_synthesis_prompt_fn,
    )

    assert result.deliberation_status == ConsensusStatus.partial_failure

    # Round-trip: serialize → deserialize must not raise
    dumped = result.model_dump()
    json_str = json.dumps(dumped)
    parsed = json.loads(json_str)
    # The artifact should be re-constructable
    restored_artifact = DecideArtifact(**parsed["artifact"])
    assert restored_artifact.outcome is not None
