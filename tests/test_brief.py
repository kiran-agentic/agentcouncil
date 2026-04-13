from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agentcouncil.adapters import AdapterError, StubAdapter
from agentcouncil.brief import (
    Brief,
    BriefBuilder,
    BriefExtractionError,
    CodeExcerpt,
    ContaminatedBriefError,
    CONTAMINATION_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_brief_json() -> str:
    """Return a JSON string with all 5 Brief fields populated with clean content."""
    return json.dumps(
        {
            "problem_statement": "System experiences high latency under load",
            "background": "The application was deployed six months ago",
            "constraints": ["must run on Python 3.12", "no new infrastructure"],
            "goals": ["reduce p99 latency below 200ms"],
            "open_questions": ["what is the primary bottleneck?"],
        }
    )


def _valid_brief() -> Brief:
    """Return a clean Brief instance for direct model tests."""
    return Brief(
        problem_statement="System experiences high latency under load",
        background="The application was deployed six months ago",
        constraints=["must run on Python 3.12", "no new infrastructure"],
        goals=["reduce p99 latency below 200ms"],
        open_questions=["what is the primary bottleneck?"],
    )


# ---------------------------------------------------------------------------
# BRIEF-01: Import and model validation
# ---------------------------------------------------------------------------


def test_import_brief_module():
    """Importing Brief, CodeExcerpt, BriefBuilder, ContaminatedBriefError, BriefExtractionError succeeds."""
    from agentcouncil.brief import (
        Brief,
        BriefBuilder,
        BriefExtractionError,
        CodeExcerpt,
        ContaminatedBriefError,
    )

    assert Brief is not None
    assert CodeExcerpt is not None
    assert BriefBuilder is not None
    assert ContaminatedBriefError is not None
    assert BriefExtractionError is not None


@pytest.mark.parametrize(
    "missing_field",
    [
        "problem_statement",
        "background",
        "constraints",
        "goals",
        "open_questions",
    ],
)
def test_brief_fields_required(missing_field):
    """Brief() with each required field missing raises ValidationError."""
    data = {
        "problem_statement": "System experiences high latency under load",
        "background": "The application was deployed six months ago",
        "constraints": ["must run on Python 3.12"],
        "goals": ["reduce p99 latency below 200ms"],
        "open_questions": ["what is the primary bottleneck?"],
    }
    del data[missing_field]
    with pytest.raises(ValidationError):
        Brief(**data)


def test_brief_json_roundtrip():
    """Brief.model_dump_json() then Brief.model_validate_json() produces identical model_dump()."""
    original = _valid_brief()
    json_str = original.model_dump_json()
    restored = Brief.model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_build_returns_brief():
    """BriefBuilder(adapter=StubAdapter(valid_json)).build('context') returns a Brief instance."""
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    brief = builder.build("some raw context")
    assert isinstance(brief, Brief)
    assert brief.problem_statement == "System experiences high latency under load"


def test_build_populates_all_fields():
    """Returned Brief has all 5 required fields as non-empty values."""
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    brief = builder.build("some raw context")
    assert brief.problem_statement
    assert brief.background
    assert len(brief.constraints) > 0
    assert len(brief.goals) > 0
    assert len(brief.open_questions) > 0


# ---------------------------------------------------------------------------
# BRIEF-02: Contamination detection — basic cases
# ---------------------------------------------------------------------------


def test_contaminated_brief_raises():
    """Brief with 'I recommend we use Redis' in problem_statement raises ContaminatedBriefError."""
    contaminated_json = json.dumps(
        {
            "problem_statement": "I recommend we use Redis for caching",
            "background": "The application was deployed six months ago",
            "constraints": ["must run on Python 3.12"],
            "goals": ["reduce p99 latency below 200ms"],
            "open_questions": ["what is the primary bottleneck?"],
        }
    )
    adapter = StubAdapter(contaminated_json)
    builder = BriefBuilder(adapter=adapter)
    with pytest.raises(ContaminatedBriefError):
        builder.build("context")


def test_clean_brief_passes():
    """Brief with no opinion language returns successfully."""
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    brief = builder.build("context")
    assert isinstance(brief, Brief)


def test_contamination_checks_all_text_fields():
    """Contamination in background, constraints, goals, or open_questions also raises."""
    fields_to_contaminate = [
        ("background", "I recommend using a queue here"),
        ("constraints", ["I suggest we use Redis instead"]),
        ("goals", ["we should adopt microservices"]),
        ("open_questions", ["I think we should use Kafka"]),
    ]
    base = {
        "problem_statement": "System experiences high latency",
        "background": "The application was deployed six months ago",
        "constraints": ["must run on Python 3.12"],
        "goals": ["reduce p99 latency"],
        "open_questions": ["what is the primary bottleneck?"],
    }
    for field, value in fields_to_contaminate:
        data = dict(base)
        data[field] = value
        contaminated_json = json.dumps(data)
        adapter = StubAdapter(contaminated_json)
        builder = BriefBuilder(adapter=adapter)
        with pytest.raises(ContaminatedBriefError):
                builder.build("context")


# ---------------------------------------------------------------------------
# BRIEF-03: Contamination patterns — parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contamination_phrase",
    [
        "I recommend using Redis for caching",
        "my suggestion is to use a queue",
        "we should adopt microservices",
        "the best approach is event sourcing",
        "you should implement a cache layer",
        "I think we should use Kafka",
        "I would implement this with async workers",
        "my preferred solution is to add an index",
        "I propose we refactor the data layer",
    ],
)
def test_each_contamination_pattern(contamination_phrase):
    """Each contamination phrase independently triggers ContaminatedBriefError."""
    contaminated_json = json.dumps(
        {
            "problem_statement": contamination_phrase,
            "background": "The application was deployed six months ago",
            "constraints": ["must run on Python 3.12"],
            "goals": ["reduce p99 latency below 200ms"],
            "open_questions": ["what is the primary bottleneck?"],
        }
    )
    adapter = StubAdapter(contaminated_json)
    builder = BriefBuilder(adapter=adapter)
    with pytest.raises(ContaminatedBriefError):
        builder.build("context")


@pytest.mark.parametrize(
    "safe_phrase",
    [
        "the team decided we should use Postgres",
        "previous design proposed using microservices",
        "engineers recommend reading the architecture doc",
    ],
)
def test_contamination_false_positive_third_party(safe_phrase):
    """Third-party attribution does NOT trigger ContaminatedBriefError."""
    safe_json = json.dumps(
        {
            "problem_statement": safe_phrase,
            "background": "The application was deployed six months ago",
            "constraints": ["must run on Python 3.12"],
            "goals": ["reduce p99 latency below 200ms"],
            "open_questions": ["what is the primary bottleneck?"],
        }
    )
    adapter = StubAdapter(safe_json)
    builder = BriefBuilder(adapter=adapter)
    brief = builder.build("context")
    assert isinstance(brief, Brief)


def test_contamination_false_positive_historical():
    """Historical reference 'previous design proposed using microservices' does NOT trigger."""
    safe_json = json.dumps(
        {
            "problem_statement": "System is slow",
            "background": "previous design proposed using microservices but was abandoned",
            "constraints": ["must run on Python 3.12"],
            "goals": ["reduce p99 latency below 200ms"],
            "open_questions": ["what is the primary bottleneck?"],
        }
    )
    adapter = StubAdapter(safe_json)
    builder = BriefBuilder(adapter=adapter)
    brief = builder.build("context")
    assert isinstance(brief, Brief)


def test_contamination_check_runs_before_return(monkeypatch):
    """Contamination check runs inside build() and is not optional — propagates when raised."""
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)

    def always_raises(brief: Brief) -> None:
        raise ContaminatedBriefError("forced contamination for test")

    monkeypatch.setattr(builder, "_check_contamination", always_raises)
    with pytest.raises(ContaminatedBriefError):
        builder.build("context")


# ---------------------------------------------------------------------------
# BRIEF-04: Code context — verbatim inclusion
# ---------------------------------------------------------------------------


def test_build_with_code_context():
    """build() with code_context=[CodeExcerpt(...)] includes code in returned Brief."""
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    excerpt = CodeExcerpt(path="src/main.py", content="print('hello')")
    brief = builder.build("some context", code_context=[excerpt])
    assert brief.code_context is not None
    assert len(brief.code_context) == 1
    assert brief.code_context[0].path == "src/main.py"


def test_code_context_verbatim():
    """Code context content is preserved exactly as provided."""
    exact_content = "def foo():\n    return 42  # magic number\n"
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    excerpt = CodeExcerpt(path="src/foo.py", content=exact_content)
    brief = builder.build("some context", code_context=[excerpt])
    assert brief.code_context[0].content == exact_content


def test_code_context_not_scanned_for_contamination():
    """CodeExcerpt content containing 'I recommend' does NOT raise ContaminatedBriefError."""
    contaminated_code = "# I recommend using this approach\ndef solution(): pass"
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    excerpt = CodeExcerpt(path="src/solution.py", content=contaminated_code)
    # Should NOT raise — code_context is caller-supplied verbatim content
    brief = builder.build("context", code_context=[excerpt])
    assert isinstance(brief, Brief)


def test_build_without_code_context():
    """build() with no code_context returns Brief with code_context=None."""
    adapter = StubAdapter(_valid_brief_json())
    builder = BriefBuilder(adapter=adapter)
    brief = builder.build("some context")
    assert brief.code_context is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_malformed_extraction_raises_brief_extraction_error():
    """StubAdapter returning non-JSON causes BriefExtractionError."""
    adapter = StubAdapter("This is not JSON at all, just some prose response.")
    builder = BriefBuilder(adapter=adapter)
    with pytest.raises(BriefExtractionError):
        builder.build("context")


def test_adapter_error_propagates():
    """AdapterError from StubAdapter propagates through build()."""

    class FailingAdapter(StubAdapter):
        def call(self, prompt: str) -> str:
            raise AdapterError("backend failure")

    builder = BriefBuilder(adapter=FailingAdapter())
    with pytest.raises(AdapterError):
        builder.build("context")


# ---------------------------------------------------------------------------
# to_prompt() tests
# ---------------------------------------------------------------------------


def test_to_prompt_returns_string():
    """Brief.to_prompt() returns a non-empty str."""
    brief = _valid_brief()
    result = brief.to_prompt()
    assert isinstance(result, str)
    assert len(result) > 0


def test_to_prompt_contains_all_sections():
    """to_prompt() output contains problem_statement, background, constraints, goals, open_questions text."""
    brief = _valid_brief()
    result = brief.to_prompt()
    assert "System experiences high latency under load" in result
    assert "The application was deployed six months ago" in result
    assert "must run on Python 3.12" in result
    assert "reduce p99 latency below 200ms" in result
    assert "what is the primary bottleneck?" in result


def test_to_prompt_includes_code_context():
    """When code_context is set, to_prompt() includes file path and content."""
    brief = Brief(
        problem_statement="System experiences high latency under load",
        background="The application was deployed six months ago",
        constraints=["must run on Python 3.12"],
        goals=["reduce p99 latency below 200ms"],
        open_questions=["what is the primary bottleneck?"],
        code_context=[CodeExcerpt(path="src/main.py", content="print('hello')")],
    )
    result = brief.to_prompt()
    assert "src/main.py" in result
    assert "print('hello')" in result


# ---------------------------------------------------------------------------
# to_prompt() structural validation
# ---------------------------------------------------------------------------


def test_to_prompt_has_correct_markdown_headings():
    """to_prompt() renders with correct H1/H2 heading hierarchy."""
    brief = _valid_brief()
    result = brief.to_prompt()
    lines = result.split("\n")
    # H1 title
    assert "# Problem Brief" in lines
    # H2 section headings in correct order
    h2_lines = [l for l in lines if l.startswith("## ")]
    expected_headings = [
        "## Problem Statement",
        "## Background",
        "## Constraints",
        "## Goals",
        "## Open Questions",
    ]
    assert h2_lines == expected_headings


def test_to_prompt_constraints_as_bullet_list():
    """to_prompt() renders constraints as markdown bullet list."""
    brief = Brief(
        problem_statement="problem",
        background="bg",
        constraints=["constraint one", "constraint two"],
        goals=["goal one"],
        open_questions=["question one"],
    )
    result = brief.to_prompt()
    assert "- constraint one" in result
    assert "- constraint two" in result


def test_to_prompt_without_code_context_no_code_heading():
    """to_prompt() with no code_context does not include Code Context heading."""
    brief = _valid_brief()
    result = brief.to_prompt()
    assert "## Code Context" not in result


def test_to_prompt_with_code_context_includes_heading():
    """to_prompt() with code_context includes Code Context heading and code fence."""
    brief = Brief(
        problem_statement="problem",
        background="bg",
        constraints=["c"],
        goals=["g"],
        open_questions=["q"],
        code_context=[CodeExcerpt(path="app.py", content="x = 1")],
    )
    result = brief.to_prompt()
    assert "## Code Context" in result
    assert "### `app.py`" in result
    assert "```" in result
    assert "x = 1" in result


# ---------------------------------------------------------------------------
# _strip_code_fences edge cases
# ---------------------------------------------------------------------------


def test_strip_code_fences_plain_json():
    """Plain JSON without fences passes through unchanged."""
    from agentcouncil.brief import _strip_code_fences
    raw = '{"key": "value"}'
    assert _strip_code_fences(raw) == raw


def test_strip_code_fences_json_block():
    """```json\\n{...}\\n``` is stripped to just the JSON content."""
    from agentcouncil.brief import _strip_code_fences
    raw = '```json\n{"key": "value"}\n```'
    assert _strip_code_fences(raw) == '{"key": "value"}'


def test_strip_code_fences_bare_block():
    """``` without language specifier is also stripped."""
    from agentcouncil.brief import _strip_code_fences
    raw = '```\n{"key": "value"}\n```'
    assert _strip_code_fences(raw) == '{"key": "value"}'


def test_strip_code_fences_with_surrounding_whitespace():
    """Fences with leading/trailing whitespace are still stripped."""
    from agentcouncil.brief import _strip_code_fences
    raw = '  \n```json\n{"key": "value"}\n```  \n'
    assert _strip_code_fences(raw) == '{"key": "value"}'


def test_strip_code_fences_no_closing_fence():
    """Missing closing fence returns text unchanged (not stripped)."""
    from agentcouncil.brief import _strip_code_fences
    raw = '```json\n{"key": "value"}'
    assert _strip_code_fences(raw) == raw


# ---------------------------------------------------------------------------
# ContaminatedBriefError details
# ---------------------------------------------------------------------------


def test_contamination_error_includes_matched_pattern():
    """ContaminatedBriefError message includes the matched pattern and matched text."""
    contaminated_json = json.dumps({
        "problem_statement": "I recommend using Redis for caching",
        "background": "bg",
        "constraints": ["c"],
        "goals": ["g"],
        "open_questions": ["q"],
    })
    adapter = StubAdapter(contaminated_json)
    builder = BriefBuilder(adapter=adapter)
    with pytest.raises(ContaminatedBriefError) as exc_info:
        builder.build("context")
    assert "I recommend" in str(exc_info.value)
    assert exc_info.value.reason  # .reason attribute is populated


def test_extraction_error_includes_original_cause():
    """BriefExtractionError message includes details about why parsing failed."""
    adapter = StubAdapter('{"problem_statement": 42}')  # wrong type
    builder = BriefBuilder(adapter=adapter)
    with pytest.raises(BriefExtractionError, match="Failed to parse"):
        builder.build("context")


def test_contamination_patterns_list_is_not_empty():
    """CONTAMINATION_PATTERNS has at least 5 patterns (safety check against accidental clearing)."""
    assert len(CONTAMINATION_PATTERNS) >= 5


def test_extraction_prompt_contains_placeholder():
    """EXTRACTION_PROMPT template contains {raw_context} placeholder."""
    from agentcouncil.brief import EXTRACTION_PROMPT
    assert "{raw_context}" in EXTRACTION_PROMPT
