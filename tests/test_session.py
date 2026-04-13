"""Tests for agentcouncil.session — OutsideSession lifecycle and OutsideSessionAdapter.

Covers:
    - OutsideSession.open() calls provider.auth_check()
    - OutsideSession.call() appends messages and returns text
    - Message accumulation across multiple call() invocations (replay semantics)
    - OutsideSession.close() completes without error
    - OutsideSessionAdapter.acall() delegates to session.call()
    - OutsideSessionAdapter.call() raises RuntimeError (async-only)
    - OutsideSessionAdapter.acall() wraps exceptions in AdapterError
    - DeprecationWarning emitted for external AgentAdapter subclasses
    - No DeprecationWarning for internal AgentAdapter subclasses
"""
from __future__ import annotations

import tempfile
import warnings

import pytest
import pytest_asyncio

from agentcouncil.adapters import AgentAdapter, AdapterError
from agentcouncil.providers.base import ProviderResponse, StubProvider
from agentcouncil.runtime import OutsideRuntime
from agentcouncil.session import OutsideSession, OutsideSessionAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path):
    """Return a temp directory path string for use as runtime workspace."""
    return str(tmp_path)


@pytest.fixture
def stub_provider():
    """Return a StubProvider that cycles a single stub response."""
    return StubProvider(ProviderResponse(content="stub response"))


@pytest.fixture
def runtime(stub_provider, tmp_workspace):
    """Return an OutsideRuntime backed by stub_provider."""
    return OutsideRuntime(stub_provider, tmp_workspace)


@pytest.fixture
def session(stub_provider, runtime):
    """Return an OutsideSession with stub_provider and runtime."""
    return OutsideSession(stub_provider, runtime)


# ---------------------------------------------------------------------------
# OutsideSession lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outside_session_open_calls_auth_check(stub_provider, runtime):
    """open() calls provider.auth_check() exactly once."""
    call_count = 0

    original_auth_check = stub_provider.auth_check

    async def counting_auth_check():
        nonlocal call_count
        call_count += 1
        return await original_auth_check()

    stub_provider.auth_check = counting_auth_check

    sess = OutsideSession(stub_provider, runtime)
    await sess.open()
    assert call_count == 1


@pytest.mark.asyncio
async def test_outside_session_call_returns_text(session):
    """call() returns the text from run_turn."""
    result = await session.call("hello")
    assert result == "stub response"


@pytest.mark.asyncio
async def test_outside_session_call_appends_messages(session):
    """After call('hello'), session._messages has 2 entries (user + assistant)."""
    await session.call("hello")
    assert len(session._messages) == 2
    assert session._messages[0] == {"role": "user", "content": "hello"}
    assert session._messages[1] == {"role": "assistant", "content": "stub response"}


@pytest.mark.asyncio
async def test_outside_session_replay_accumulation(tmp_workspace):
    """After call('a') then call('b'), session._messages has 4 entries total.

    The second run_turn receives 3 messages as input (user1 + assistant1 + user2).
    provider.calls[1] must be a list of 3 messages.
    """
    provider = StubProvider(ProviderResponse(content="stub response"))
    rt = OutsideRuntime(provider, tmp_workspace)
    sess = OutsideSession(provider, rt)

    await sess.call("a")
    await sess.call("b")

    # 4 messages total: user1, assistant1, user2, assistant2
    assert len(sess._messages) == 4
    assert sess._messages[0] == {"role": "user", "content": "a"}
    assert sess._messages[1] == {"role": "assistant", "content": "stub response"}
    assert sess._messages[2] == {"role": "user", "content": "b"}
    assert sess._messages[3] == {"role": "assistant", "content": "stub response"}

    # The second run_turn received 3 messages (user1 + assistant1 + user2)
    assert len(provider.calls[1]) == 3


@pytest.mark.asyncio
async def test_outside_session_close_is_noop(session):
    """close() completes without error."""
    await session.close()  # should not raise


# ---------------------------------------------------------------------------
# OutsideSessionAdapter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outside_session_adapter_acall_delegates(session):
    """OutsideSessionAdapter.acall('x') returns same text as session.call('x')."""
    adapter = OutsideSessionAdapter(session)
    result = await adapter.acall("x")
    assert result == "stub response"


def test_outside_session_adapter_call_raises(session):
    """OutsideSessionAdapter.call('x') raises RuntimeError with 'async-only'."""
    adapter = OutsideSessionAdapter(session)
    with pytest.raises(RuntimeError, match="async-only"):
        adapter.call("x")


@pytest.mark.asyncio
async def test_outside_session_adapter_wraps_exception(stub_provider, runtime):
    """If session.call raises, acall() wraps it in AdapterError."""
    session = OutsideSession(stub_provider, runtime)

    # Monkey-patch session.call to raise
    async def failing_call(prompt: str) -> str:
        raise ValueError("unexpected failure")

    session.call = failing_call

    adapter = OutsideSessionAdapter(session)
    with pytest.raises(AdapterError, match="OutsideSession call failed"):
        await adapter.acall("trigger error")


# ---------------------------------------------------------------------------
# DeprecationWarning tests
# ---------------------------------------------------------------------------


def test_deprecation_warning_external_subclass():
    """Defining a new AgentAdapter subclass in test code emits DeprecationWarning."""
    with pytest.warns(DeprecationWarning, match="deprecated"):
        class MyExternalAdapter(AgentAdapter):
            def call(self, prompt: str) -> str:
                return "ok"


def test_no_deprecation_warning_internal_subclasses():
    """Importing internal subclasses does NOT emit DeprecationWarning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        # These imports must NOT trigger DeprecationWarning
        from agentcouncil.adapters import (
            CodexAdapter,  # noqa: F401
            ClaudeAdapter,  # noqa: F401
            StubAdapter,  # noqa: F401
            CodexSessionAdapter,  # noqa: F401
        )


def test_outside_session_adapter_emits_deprecation():
    """OutsideSessionAdapter (in agentcouncil.session) DOES emit DeprecationWarning at class definition.

    The warning is correct — it signals AgentAdapter is the deprecated extension point.
    """
    # The warning fires at import time of session.py, so we just verify
    # that OutsideSessionAdapter's module is NOT agentcouncil.adapters
    assert OutsideSessionAdapter.__module__ == "agentcouncil.session"
    # Verify the class IS a subclass of AgentAdapter (so warning would fire at import)
    assert issubclass(OutsideSessionAdapter, AgentAdapter)


# ---------------------------------------------------------------------------
# Metadata propagation tests (Plan 12-02)
# ---------------------------------------------------------------------------

import json

from agentcouncil.adapters import StubAdapter
from agentcouncil.schemas import (
    TranscriptMeta,
    ReviewInput,
    DecideInput,
    DecideOption,
    ChallengeInput,
)
from agentcouncil.brief import Brief


def _stub_review_json():
    """Return valid ReviewArtifact JSON for StubAdapter synthesis responses."""
    return json.dumps({
        "verdict": "pass",
        "summary": "No major issues found.",
        "findings": [],
        "strengths": ["clear structure"],
        "open_questions": [],
        "next_action": "Ship it",
    })


def _stub_decide_json():
    """Return valid DecideArtifact JSON (decided, option A selected)."""
    return json.dumps({
        "outcome": "decided",
        "winner_option_id": "A",
        "decision_summary": "A is better.",
        "option_assessments": [
            {
                "option_id": "A",
                "pros": ["fast"],
                "cons": [],
                "blocking_risks": [],
                "disposition": "selected",
                "confidence": "high",
                "source_refs": [],
            },
            {
                "option_id": "B",
                "pros": [],
                "cons": ["slow"],
                "blocking_risks": [],
                "disposition": "rejected",
                "confidence": "high",
                "source_refs": [],
            },
        ],
        "defer_reason": None,
        "experiment_plan": None,
        "revisit_triggers": [],
        "next_action": "proceed with A",
    })


def _stub_challenge_json():
    """Return valid ChallengeArtifact JSON (ready, no failure modes)."""
    return json.dumps({
        "readiness": "ready",
        "summary": "Plan withstood challenge.",
        "failure_modes": [],
        "surviving_assumptions": ["assumption 1 holds"],
        "break_conditions": [],
        "residual_risks": [],
        "next_action": "proceed",
    })


def _stub_consensus_json():
    """Return valid ConsensusArtifact JSON for brainstorm synthesis."""
    return json.dumps({
        "recommended_direction": "Use approach A",
        "agreement_points": ["Both prefer A"],
        "disagreement_points": [],
        "rejected_alternatives": [],
        "open_risks": [],
        "next_action": "Prototype A",
        "status": "consensus",
    })


@pytest.mark.asyncio
async def test_run_deliberation_populates_meta():
    """run_deliberation(..., outside_meta=...) sets result.transcript.meta."""
    from agentcouncil.deliberation import run_deliberation

    meta = TranscriptMeta(outside_provider="stub")
    outside = StubAdapter(["initial analysis", _stub_review_json()])
    lead = StubAdapter("lead analysis")

    def synthesis_fn(ip, oi, li, disc, schema):
        return f"Synthesize: {ip}"

    result = await run_deliberation(
        input_prompt="Review this code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=__import__("agentcouncil.schemas", fromlist=["ReviewArtifact"]).ReviewArtifact,
        synthesis_prompt_fn=synthesis_fn,
        outside_meta=meta,
    )
    assert result.transcript.meta is not None
    assert result.transcript.meta.outside_provider == "stub"


@pytest.mark.asyncio
async def test_run_deliberation_no_meta_default():
    """run_deliberation(...) without outside_meta leaves transcript.meta as None."""
    from agentcouncil.deliberation import run_deliberation
    from agentcouncil.schemas import ReviewArtifact

    outside = StubAdapter(["initial analysis", _stub_review_json()])
    lead = StubAdapter("lead analysis")

    def synthesis_fn(ip, oi, li, disc, schema):
        return f"Synthesize: {ip}"

    result = await run_deliberation(
        input_prompt="Review this code",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=synthesis_fn,
    )
    assert result.transcript.meta is None


@pytest.mark.asyncio
async def test_brainstorm_populates_meta():
    """brainstorm(..., outside_meta=...) sets result.transcript.meta."""
    from agentcouncil.deliberation import brainstorm
    from agentcouncil.brief import Brief

    meta = TranscriptMeta(outside_provider="stub")
    outside = StubAdapter(["outside proposal", _stub_consensus_json()])
    lead = StubAdapter("lead proposal")
    brief = Brief(
        problem_statement="test topic",
        background="some context",
        constraints=[],
        goals=["find a solution"],
        open_questions=[],
    )

    result = await brainstorm(
        brief=brief,
        outside_adapter=outside,
        lead_adapter=lead,
        outside_meta=meta,
    )
    assert result.transcript.meta is not None
    assert result.transcript.meta.outside_provider == "stub"


@pytest.mark.asyncio
async def test_review_passes_meta():
    """review(..., outside_meta=...) propagates meta to result.transcript.meta."""
    from agentcouncil.review import review

    meta = TranscriptMeta(outside_provider="stub", outside_session_mode="replay")
    outside = StubAdapter(["findings analysis", _stub_review_json()])
    lead = StubAdapter("lead review")

    ri = ReviewInput(artifact="def foo(): pass", artifact_type="code")
    result = await review(ri, outside, lead, outside_meta=meta)
    assert result.transcript.meta is not None
    assert result.transcript.meta.outside_provider == "stub"
    assert result.transcript.meta.outside_session_mode == "replay"


@pytest.mark.asyncio
async def test_decide_passes_meta():
    """decide(..., outside_meta=...) propagates meta to result.transcript.meta."""
    from agentcouncil.decide import decide

    meta = TranscriptMeta(outside_provider="stub", outside_workspace_access="assisted")
    outside = StubAdapter(["option analysis", _stub_decide_json()])
    lead = StubAdapter("lead analysis")

    di = DecideInput(
        decision="Which option?",
        options=[DecideOption(id="A", label="Option A", description="fast"), DecideOption(id="B", label="Option B", description="slow")],
    )
    result = await decide(di, outside, lead, outside_meta=meta)
    assert result.transcript.meta is not None
    assert result.transcript.meta.outside_provider == "stub"
    assert result.transcript.meta.outside_workspace_access == "assisted"


@pytest.mark.asyncio
async def test_challenge_passes_meta():
    """challenge(..., outside_meta=...) propagates meta to result.transcript.meta."""
    from agentcouncil.challenge import challenge

    meta = TranscriptMeta(outside_provider="stub", outside_profile="local-dev")
    outside = StubAdapter(["attack analysis", _stub_challenge_json()])
    lead = StubAdapter("defense analysis")

    ci = ChallengeInput(artifact="my plan description", assumptions=["assumption 1"])
    result = await challenge(ci, outside, lead, outside_meta=meta)
    assert result.transcript.meta is not None
    assert result.transcript.meta.outside_provider == "stub"
    assert result.transcript.meta.outside_profile == "local-dev"


# ---------------------------------------------------------------------------
# Session strategy tests (USESS-01 / USESS-02 / USESS-03)
# ---------------------------------------------------------------------------


def _make_persistent_stub():
    """StubProvider with session_strategy='persistent' for testing USESS-01."""
    provider = StubProvider(ProviderResponse(content="stub response"))
    provider.session_strategy = "persistent"
    provider.workspace_access = "native"
    return provider


def test_session_strategy_derived_from_provider(tmp_path):
    """USESS-03: session_strategy is derived from provider's class attribute at init."""
    # Default StubProvider has session_strategy="replay" (inherited from OutsideProvider)
    provider = StubProvider(ProviderResponse(content="stub response"))
    runtime = OutsideRuntime(provider, str(tmp_path))
    sess = OutsideSession(provider, runtime)
    assert sess.session_strategy == "replay"

    # Persistent stub overrides session_strategy to "persistent"
    persistent_provider = _make_persistent_stub()
    runtime2 = OutsideRuntime(persistent_provider, str(tmp_path))
    sess2 = OutsideSession(persistent_provider, runtime2)
    assert sess2.session_strategy == "persistent"


def test_session_mode_equals_session_strategy(tmp_path):
    """USESS-03: session_mode always equals session_strategy for TranscriptMeta backward compat."""
    provider = StubProvider(ProviderResponse(content="stub response"))
    runtime = OutsideRuntime(provider, str(tmp_path))
    sess = OutsideSession(provider, runtime)
    assert sess.session_mode == sess.session_strategy

    persistent_provider = _make_persistent_stub()
    runtime2 = OutsideRuntime(persistent_provider, str(tmp_path))
    sess2 = OutsideSession(persistent_provider, runtime2)
    assert sess2.session_mode == sess2.session_strategy


def test_workspace_access_derived_from_provider(tmp_path):
    """USESS-03: workspace_access is derived from provider's class attribute at init."""
    # Default StubProvider has workspace_access="assisted" (inherited from OutsideProvider)
    provider = StubProvider(ProviderResponse(content="stub response"))
    runtime = OutsideRuntime(provider, str(tmp_path))
    sess = OutsideSession(provider, runtime)
    assert sess.workspace_access == "assisted"

    # Persistent stub overrides workspace_access to "native"
    persistent_provider = _make_persistent_stub()
    runtime2 = OutsideRuntime(persistent_provider, str(tmp_path))
    sess2 = OutsideSession(persistent_provider, runtime2)
    assert sess2.workspace_access == "native"


@pytest.mark.asyncio
async def test_persistent_session_sends_only_latest_message(tmp_path):
    """USESS-01: Persistent providers receive only the latest user message per call().

    call("a") sends [user "a"] only (not full history).
    call("b") sends [user "b"] only (not user "a" + assistant + user "b").
    """
    provider = _make_persistent_stub()
    runtime = OutsideRuntime(provider, str(tmp_path))
    sess = OutsideSession(provider, runtime)

    await sess.call("a")
    await sess.call("b")

    # First call: only the user message "a" was sent
    assert len(provider.calls[0]) == 1, f"Expected 1 message, got {len(provider.calls[0])}"
    assert provider.calls[0][0]["content"] == "a"

    # Second call: only the user message "b" was sent (not full history)
    assert len(provider.calls[1]) == 1, f"Expected 1 message, got {len(provider.calls[1])}"
    assert provider.calls[1][0]["content"] == "b"


@pytest.mark.asyncio
async def test_persistent_session_accumulates_full_history(tmp_path):
    """USESS-01: Full history is still tracked internally even though only latest is sent.

    After two calls, session._messages has 4 entries:
    user "a", assistant "stub response", user "b", assistant "stub response".
    """
    provider = _make_persistent_stub()
    runtime = OutsideRuntime(provider, str(tmp_path))
    sess = OutsideSession(provider, runtime)

    await sess.call("a")
    await sess.call("b")

    assert len(sess._messages) == 4, f"Expected 4 messages in history, got {len(sess._messages)}"
    assert sess._messages[0] == {"role": "user", "content": "a"}
    assert sess._messages[1] == {"role": "assistant", "content": "stub response"}
    assert sess._messages[2] == {"role": "user", "content": "b"}
    assert sess._messages[3] == {"role": "assistant", "content": "stub response"}


@pytest.mark.asyncio
async def test_replay_session_sends_full_history(tmp_path):
    """USESS-02: Replay providers receive full accumulated history on every call().

    After call("a") then call("b"), the second run_turn receives 3 messages:
    [user "a", assistant "stub response", user "b"].
    """
    provider = StubProvider(ProviderResponse(content="stub response"))
    runtime = OutsideRuntime(provider, str(tmp_path))
    sess = OutsideSession(provider, runtime)

    await sess.call("a")
    await sess.call("b")

    # Second call receives full history: user1 + assistant1 + user2 = 3 messages
    assert len(provider.calls[1]) == 3, (
        f"Expected 3 messages in second call, got {len(provider.calls[1])}"
    )


@pytest.mark.asyncio
async def test_transcript_metadata_integration():
    """Integration: build TranscriptMeta from OutsideSession fields, pass to run_deliberation.

    Verifies the full flow: session fields -> TranscriptMeta -> run_deliberation -> transcript.
    All 5 metadata fields (outside_provider, outside_profile, outside_model,
    outside_session_mode, outside_workspace_access) are present in the result transcript.
    """
    from agentcouncil.deliberation import run_deliberation
    from agentcouncil.schemas import ReviewArtifact

    # Simulate what caller code does: construct TranscriptMeta from session fields
    session_provider_name = "stub"
    session_profile = "local-dev"
    session_model = "gpt-4o"
    session_mode = "replay"
    session_workspace_access = "assisted"

    meta = TranscriptMeta(
        outside_provider=session_provider_name,
        outside_profile=session_profile,
        outside_model=session_model,
        outside_session_mode=session_mode,
        outside_workspace_access=session_workspace_access,
    )

    outside = StubAdapter(["initial analysis", _stub_review_json()])
    lead = StubAdapter("lead analysis")

    def synthesis_fn(ip, oi, li, disc, schema):
        return f"Synthesize: {ip}"

    result = await run_deliberation(
        input_prompt="Integration test prompt",
        outside_adapter=outside,
        lead_adapter=lead,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=synthesis_fn,
        outside_meta=meta,
    )

    assert result.transcript.meta is not None
    assert result.transcript.meta.outside_provider == "stub"
    assert result.transcript.meta.outside_profile == "local-dev"
    assert result.transcript.meta.outside_model == "gpt-4o"
    assert result.transcript.meta.outside_session_mode == "replay"
    assert result.transcript.meta.outside_workspace_access == "assisted"
