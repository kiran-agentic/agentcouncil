"""Tests for Review schema models (REV-01 through REV-06)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# ReviewInput tests (REV-01, REV-11)
# ---------------------------------------------------------------------------


def test_review_input_minimal():
    """ReviewInput(artifact='some code') succeeds with defaults."""
    from agentcouncil.schemas import ReviewInput

    ri = ReviewInput(artifact="some code")
    assert ri.artifact == "some code"
    assert ri.artifact_type == "other"
    assert ri.review_objective is None
    assert ri.focus_areas == []
    assert ri.rounds == 1


def test_review_input_full():
    """ReviewInput with all optional fields set succeeds."""
    from agentcouncil.schemas import ReviewInput

    ri = ReviewInput(
        artifact="def foo(): pass",
        artifact_type="code",
        review_objective="security",
        focus_areas=["auth", "input validation"],
        rounds=2,
    )
    assert ri.artifact_type == "code"
    assert ri.review_objective == "security"
    assert ri.focus_areas == ["auth", "input validation"]
    assert ri.rounds == 2


def test_review_input_artifact_type_values():
    """artifact_type accepts code/design/plan/document/other only."""
    from agentcouncil.schemas import ReviewInput

    for at in ("code", "design", "plan", "document", "other"):
        ri = ReviewInput(artifact="x", artifact_type=at)
        assert ri.artifact_type == at

    with pytest.raises(ValidationError):
        ReviewInput(artifact="x", artifact_type="spreadsheet")


def test_review_input_artifact_required():
    """ReviewInput() without artifact raises ValidationError."""
    from agentcouncil.schemas import ReviewInput

    with pytest.raises(ValidationError):
        ReviewInput()


def test_review_input_rounds_default():
    """ReviewInput(artifact='x').rounds == 1 (REV-11 default)."""
    from agentcouncil.schemas import ReviewInput

    ri = ReviewInput(artifact="x")
    assert ri.rounds == 1


# ---------------------------------------------------------------------------
# Finding tests (REV-04, REV-05, REV-06)
# ---------------------------------------------------------------------------


def _make_finding(**overrides):
    """Helper: build a valid Finding dict, applying overrides."""
    base = dict(
        id="F-001",
        title="SQL injection risk",
        severity="high",
        impact="Data exfiltration possible",
        description="User input passed directly to query",
        evidence="Line 42: query(f'SELECT * FROM {user_input}')",
        locations=["src/db.py:42"],
        confidence="high",
        agreement="confirmed",
        origin="outside",
    )
    base.update(overrides)
    return base


def test_finding_model():
    """Finding with all 12 fields succeeds."""
    from agentcouncil.schemas import Finding, SourceRef

    f = Finding(
        **_make_finding(
            source_refs=[SourceRef(label="file", path="src/db.py")],
            priority="P1",
        )
    )
    assert f.id == "F-001"
    assert f.title == "SQL injection risk"
    assert f.severity == "high"
    assert f.impact == "Data exfiltration possible"
    assert f.description == "User input passed directly to query"
    assert f.evidence == "Line 42: query(f'SELECT * FROM {user_input}')"
    assert f.locations == ["src/db.py:42"]
    assert f.confidence == "high"
    assert f.agreement == "confirmed"
    assert f.origin == "outside"
    assert len(f.source_refs) == 1
    assert f.priority == "P1"


def test_finding_severity_values():
    """severity accepts critical/high/medium/low only."""
    from agentcouncil.schemas import Finding

    for sev in ("critical", "high", "medium", "low"):
        f = Finding(**_make_finding(severity=sev))
        assert f.severity == sev

    with pytest.raises(ValidationError):
        Finding(**_make_finding(severity="info"))


def test_finding_confidence_values():
    """confidence accepts high/medium/low only."""
    from agentcouncil.schemas import Finding

    for conf in ("high", "medium", "low"):
        f = Finding(**_make_finding(confidence=conf))
        assert f.confidence == conf

    with pytest.raises(ValidationError):
        Finding(**_make_finding(confidence="uncertain"))


def test_finding_agreement_values():
    """agreement accepts confirmed/disputed only."""
    from agentcouncil.schemas import Finding

    for agr in ("confirmed", "disputed"):
        f = Finding(**_make_finding(agreement=agr))
        assert f.agreement == agr

    with pytest.raises(ValidationError):
        Finding(**_make_finding(agreement="unknown"))


def test_finding_origin_values():
    """origin accepts outside/lead/both only."""
    from agentcouncil.schemas import Finding

    for orig in ("outside", "lead", "both"):
        f = Finding(**_make_finding(origin=orig))
        assert f.origin == orig

    with pytest.raises(ValidationError):
        Finding(**_make_finding(origin="director"))


def test_finding_priority_optional():
    """Finding without priority succeeds (priority defaults to None)."""
    from agentcouncil.schemas import Finding

    f = Finding(**_make_finding())
    assert f.priority is None


def test_finding_source_refs_uses_source_ref():
    """Finding.source_refs is list[SourceRef]."""
    from agentcouncil.schemas import Finding, SourceRef

    ref = SourceRef(label="docs", url="https://example.com")
    f = Finding(**_make_finding(source_refs=[ref]))
    assert len(f.source_refs) == 1
    assert isinstance(f.source_refs[0], SourceRef)
    assert f.source_refs[0].label == "docs"


def test_finding_locations_list_str():
    """Finding.locations is list[str]."""
    from agentcouncil.schemas import Finding

    f = Finding(**_make_finding(locations=["file.py:10", "file.py:20"]))
    assert f.locations == ["file.py:10", "file.py:20"]
    assert all(isinstance(loc, str) for loc in f.locations)


# ---------------------------------------------------------------------------
# Updated ReviewArtifact tests (REV-02)
# ---------------------------------------------------------------------------


def test_review_artifact_findings_typed():
    """ReviewArtifact.findings is list[Finding] (not list[dict])."""
    from agentcouncil.schemas import Finding, ReviewArtifact

    finding = Finding(**_make_finding())
    ra = ReviewArtifact(
        verdict="revise",
        summary="Issues found",
        findings=[finding],
        next_action="Fix issues",
    )
    assert len(ra.findings) == 1
    assert isinstance(ra.findings[0], Finding)


def test_review_artifact_json_roundtrip_with_findings():
    """Full ReviewArtifact with typed Finding objects survives JSON roundtrip."""
    from agentcouncil.schemas import Finding, ReviewArtifact, SourceRef

    finding = Finding(
        **_make_finding(
            source_refs=[SourceRef(label="f", path="a.py")],
            priority="P2",
        )
    )
    original = ReviewArtifact(
        verdict="revise",
        summary="Needs work",
        findings=[finding],
        strengths=["Clean code"],
        open_questions=["Perf?"],
        next_action="Fix bugs",
    )
    json_str = original.model_dump_json()
    restored = ReviewArtifact.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()
    assert isinstance(restored.findings[0], Finding)
    assert restored.findings[0].priority == "P2"


def test_review_artifact_backward_compat():
    """ReviewArtifact(verdict='pass', summary='s', next_action='a') still works."""
    from agentcouncil.schemas import ReviewArtifact

    ra = ReviewArtifact(verdict="pass", summary="s", next_action="a")
    assert ra.verdict == "pass"
    assert ra.findings == []
    assert ra.strengths == []
    assert ra.open_questions == []


# ---------------------------------------------------------------------------
# review() function tests (REV-07 through REV-11)
# ---------------------------------------------------------------------------

import asyncio
import json

from agentcouncil.adapters import StubAdapter, AdapterError
from agentcouncil.schemas import (
    DeliberationResult,
    ReviewArtifact,
    ReviewInput,
    Finding,
)


def _make_valid_review_json():
    """Return a valid ReviewArtifact JSON string with typed Finding objects."""
    return json.dumps({
        "verdict": "revise",
        "summary": "Found issues in error handling",
        "findings": [{
            "id": "F-001",
            "title": "Missing null check",
            "severity": "high",
            "impact": "Runtime crash on None input",
            "description": "Function process() does not validate input",
            "evidence": "Line 42: result = input.strip()",
            "locations": ["src/process.py:42"],
            "confidence": "high",
            "agreement": "confirmed",
            "origin": "outside",
            "source_refs": [],
        }],
        "strengths": ["Clean separation of concerns"],
        "open_questions": ["Performance under load?"],
        "next_action": "Fix null check in process()",
    })


async def test_review_returns_envelope():
    """review() with StubAdapters returns DeliberationResult[ReviewArtifact] with verdict, findings, strengths."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside review analysis", valid_json])
    lead = StubAdapter(responses=["Lead review analysis"])

    ri = ReviewInput(artifact="def process(x): return x.strip()", artifact_type="code")
    result = await review(ri, outside, lead)

    assert isinstance(result, DeliberationResult)
    assert isinstance(result.artifact, ReviewArtifact)
    assert result.artifact.verdict == "revise"
    assert len(result.artifact.findings) == 1
    assert isinstance(result.artifact.findings[0], Finding)
    assert result.artifact.strengths == ["Clean separation of concerns"]


async def test_review_transcript_populated():
    """result.transcript has input_prompt, outside_initial, lead_initial populated."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside analysis here", valid_json])
    lead = StubAdapter(responses=["Lead analysis here"])

    ri = ReviewInput(artifact="some code")
    result = await review(ri, outside, lead)

    assert result.transcript.input_prompt  # non-empty
    assert result.transcript.outside_initial == "Outside analysis here"
    assert result.transcript.lead_initial == "Lead analysis here"


async def test_review_default_one_round():
    """review() with default rounds makes 2 outside calls (initial + synthesis) and 1 lead call (REV-11)."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside initial", valid_json])
    lead = StubAdapter(responses=["Lead initial"])

    ri = ReviewInput(artifact="some code")
    result = await review(ri, outside, lead)

    # Outside: initial + synthesis = 2 calls
    assert len(outside.calls) == 2
    # Lead: initial only = 1 call
    assert len(lead.calls) == 1
    # No exchanges
    assert len(result.transcript.exchanges) == 0


async def test_review_context_included_in_prompt():
    """review_context is included as factual context before the reviewer explores."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside initial", valid_json])
    lead = StubAdapter(responses=["Lead initial"])

    ri = ReviewInput(
        artifact="some code",
        review_context="Context pack: use vitest run; relevant file src/live.ts",
    )
    await review(ri, outside, lead)

    assert "Context pack: use vitest run" in outside.calls[0]


async def test_review_input_prompt_factual_only():
    """The input_prompt sent to adapters contains artifact content but NOT opinion language (REV-10, REV-07)."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    ri = ReviewInput(
        artifact="def foo(): pass",
        artifact_type="code",
        review_objective="security audit",
        focus_areas=["input validation", "auth"],
    )
    result = await review(ri, outside, lead)

    # The input_prompt (first call to both adapters) should contain factual content
    input_prompt = outside.calls[0]
    assert "def foo(): pass" in input_prompt
    assert "code" in input_prompt
    assert "security audit" in input_prompt
    assert "input validation" in input_prompt
    assert "auth" in input_prompt

    # Must NOT contain opinion language (REV-10)
    for phrase in ["I think", "my assessment", "I recommend", "I believe", "in my opinion"]:
        assert phrase.lower() not in input_prompt.lower(), f"Found opinion language: '{phrase}'"


async def test_review_synthesis_prompt_evaluative():
    """The synthesis prompt instructs 'state impact, not fixes' and 'do NOT include implementation recommendations' (REV-07)."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    ri = ReviewInput(artifact="some code")
    result = await review(ri, outside, lead)

    # The synthesis call is the last call to outside adapter (call index 1)
    synthesis_prompt = outside.calls[1]
    assert "impact" in synthesis_prompt.lower()
    assert "not" in synthesis_prompt.lower() and "fix" in synthesis_prompt.lower()


async def test_review_synthesis_prompt_disputed_preserved():
    """The synthesis prompt instructs 'preserve disputed findings -- do NOT collapse into consensus' (REV-09)."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    ri = ReviewInput(artifact="some code")
    result = await review(ri, outside, lead)

    synthesis_prompt = outside.calls[1]
    assert "disputed" in synthesis_prompt.lower()
    assert "preserve" in synthesis_prompt.lower() or "do not collapse" in synthesis_prompt.lower()


async def test_review_synthesis_prompt_lead_actions():
    """The synthesis prompt instructs the lead can 'confirm, dispute, or add omitted findings' (REV-08)."""
    from agentcouncil.review import review

    valid_json = _make_valid_review_json()
    outside = StubAdapter(responses=["Outside view", valid_json])
    lead = StubAdapter(responses=["Lead view"])

    ri = ReviewInput(artifact="some code")
    result = await review(ri, outside, lead)

    synthesis_prompt = outside.calls[1]
    assert "confirm" in synthesis_prompt.lower()
    assert "dispute" in synthesis_prompt.lower() or "disputed" in synthesis_prompt.lower()
    assert "add" in synthesis_prompt.lower() or "omitted" in synthesis_prompt.lower()


async def test_review_partial_failure():
    """review() with failing outside adapter returns partial_failure."""
    from agentcouncil.review import review

    class FailingAdapter(StubAdapter):
        def call(self, prompt):
            self.calls.append(prompt)
            raise AdapterError("outside crashed")

    outside = FailingAdapter(responses=[])
    lead = StubAdapter(responses=["Lead should not be called"])

    ri = ReviewInput(artifact="some code")
    result = await review(ri, outside, lead)

    assert result.deliberation_status == "partial_failure"


async def test_review_validates_input():
    """review() with empty artifact raises ValueError."""
    from agentcouncil.review import review

    outside = StubAdapter(responses=["Should not be called"])
    lead = StubAdapter(responses=["Should not be called"])

    ri = ReviewInput(artifact="")
    with pytest.raises(ValueError):
        await review(ri, outside, lead)

    # No adapter calls should have been made
    assert len(outside.calls) == 0
    assert len(lead.calls) == 0
