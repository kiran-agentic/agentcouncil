"""Tests for agentcouncil.certifier — CertificationResult, CertificationCache,
ConformanceCertifier, check_certification_gate, warn_stale_certification.

Covers CERT-01, CERT-02, CERT-03.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agentcouncil.providers.base import (
    ProviderResponse,
    StubProvider,
    ToolCall,
)
from agentcouncil.certifier import (
    CertificationCache,
    CertificationResult,
    ConformanceCertifier,
    check_certification_gate,
    warn_stale_certification,
    _get_agentcouncil_version,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    *,
    model_id: str = "test-model",
    tool_use: bool = True,
    multi_turn_coherence: bool = True,
    structured_output: bool = True,
    budget_adherence: bool = True,
    agentcouncil_version: str | None = None,
) -> CertificationResult:
    """Build a CertificationResult with sensible defaults."""
    version = agentcouncil_version if agentcouncil_version is not None else _get_agentcouncil_version()
    return CertificationResult(
        model_id=model_id,
        agentcouncil_version=version,
        certified_at="2026-04-13T00:00:00",
        tool_use=tool_use,
        multi_turn_coherence=multi_turn_coherence,
        structured_output=structured_output,
        budget_adherence=budget_adherence,
    )


# ---------------------------------------------------------------------------
# CertificationResult model tests
# ---------------------------------------------------------------------------


def test_certification_result_fields() -> None:
    """CertificationResult stores all 4 boolean dimensions."""
    result = _make_result()
    assert result.model_id == "test-model"
    assert result.tool_use is True
    assert result.multi_turn_coherence is True
    assert result.structured_output is True
    assert result.budget_adherence is True


def test_certification_result_supports_tools_property() -> None:
    """supports_tools is True when tool_use is True."""
    result = _make_result(tool_use=True)
    assert result.supports_tools is True


def test_certification_result_is_prompt_only_property() -> None:
    """is_prompt_only is True when tool_use is False."""
    result = _make_result(tool_use=False)
    assert result.is_prompt_only is True
    assert result.supports_tools is False


def test_certification_result_cache_key_format() -> None:
    """cache_key is model_id::provider_version::agentcouncil_version."""
    result = _make_result(model_id="gpt-4o")
    key = result.cache_key
    assert key.startswith("gpt-4o::unknown::")
    assert key.count("::") == 2


def test_certification_result_pydantic_serialization() -> None:
    """CertificationResult can round-trip through model_dump/model_validate."""
    result = _make_result(model_id="llama3")
    data = result.model_dump()
    restored = CertificationResult.model_validate(data)
    assert restored.model_id == result.model_id
    assert restored.tool_use == result.tool_use
    assert restored.cache_key == result.cache_key


# ---------------------------------------------------------------------------
# CertificationCache tests
# ---------------------------------------------------------------------------


def test_cache_round_trip(tmp_path: Path) -> None:
    """CertificationCache.save() then load() preserves all CertificationResult fields."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="cache-model")
    cache.save(result)

    loaded = cache.load(
        model_id="cache-model",
        provider_version="unknown",
        agentcouncil_version=result.agentcouncil_version,
    )
    assert loaded is not None
    assert loaded.model_id == result.model_id
    assert loaded.tool_use == result.tool_use
    assert loaded.multi_turn_coherence == result.multi_turn_coherence
    assert loaded.structured_output == result.structured_output
    assert loaded.budget_adherence == result.budget_adherence
    assert loaded.certified_at == result.certified_at


def test_cache_miss_returns_none(tmp_path: Path) -> None:
    """CertificationCache.load() for nonexistent model returns None."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = cache.load(model_id="not-there")
    assert result is None


def test_cache_save_creates_json_file(tmp_path: Path) -> None:
    """Saving a result creates certifications.json in the cache directory."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="file-test")
    cache.save(result)
    cert_file = tmp_path / "certifications.json"
    assert cert_file.exists()
    data = json.loads(cert_file.read_text())
    assert isinstance(data, dict)
    assert len(data) == 1


def test_cache_load_by_model_returns_any_version(tmp_path: Path) -> None:
    """load_by_model() returns any cert for a model regardless of version."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="my-model", agentcouncil_version="0.1.0")
    cache.save(result)
    loaded = cache.load_by_model("my-model")
    assert loaded is not None
    assert loaded.model_id == "my-model"


def test_cache_load_by_model_returns_none_for_unknown(tmp_path: Path) -> None:
    """load_by_model() returns None when no cert exists for the model."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = cache.load_by_model("unknown-model")
    assert result is None


def test_cache_multiple_models(tmp_path: Path) -> None:
    """Cache stores multiple models in the same JSON file."""
    cache = CertificationCache(cache_dir=tmp_path)
    cache.save(_make_result(model_id="model-a"))
    cache.save(_make_result(model_id="model-b"))
    cert_file = tmp_path / "certifications.json"
    data = json.loads(cert_file.read_text())
    assert len(data) == 2


# ---------------------------------------------------------------------------
# ConformanceCertifier tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_certifier_returns_result(tmp_path: Path) -> None:
    """ConformanceCertifier.certify() returns CertificationResult with all 4 booleans and model_id."""
    # Enough responses to cover all 4 certification scenarios
    provider = StubProvider([
        # tool_use scenario: call with tool, then response
        ProviderResponse(tool_calls=[ToolCall(id="c0", name="list_files", arguments={})]),
        ProviderResponse(content="README.md"),
        # multi_turn scenario: two turns
        ProviderResponse(content="Remembered ALPHA-42"),
        ProviderResponse(content="The token is ALPHA-42"),
        # structured_output scenario
        ProviderResponse(content='{"status": "ok"}'),
        # budget scenario
        ProviderResponse(content="Short response"),
    ])
    certifier = ConformanceCertifier(provider=provider, model_id="test-model", workspace=str(tmp_path))
    result = await certifier.certify()
    assert isinstance(result, CertificationResult)
    assert result.model_id == "test-model"
    assert isinstance(result.tool_use, bool)
    assert isinstance(result.multi_turn_coherence, bool)
    assert isinstance(result.structured_output, bool)
    assert isinstance(result.budget_adherence, bool)


@pytest.mark.asyncio
async def test_certifier_tool_use_detected(tmp_path: Path) -> None:
    """StubProvider that returns a ToolCall response yields tool_use=True."""
    provider = StubProvider([
        ProviderResponse(tool_calls=[ToolCall(id="c0", name="list_files", arguments={})]),
        ProviderResponse(content="README.md"),
        # multi_turn
        ProviderResponse(content="Remembered ALPHA-42"),
        ProviderResponse(content="The token is ALPHA-42"),
        # structured_output
        ProviderResponse(content='{"status": "ok"}'),
        # budget
        ProviderResponse(content="Short response"),
    ])
    certifier = ConformanceCertifier(provider=provider, model_id="tool-model", workspace=str(tmp_path))
    result = await certifier.certify()
    assert result.tool_use is True


@pytest.mark.asyncio
async def test_certifier_tool_use_false_for_text_only(tmp_path: Path) -> None:
    """StubProvider returning only text yields tool_use=False."""
    # Single cycling response — no tool calls ever
    provider = StubProvider(ProviderResponse(content="I cannot use tools"))
    certifier = ConformanceCertifier(provider=provider, model_id="text-only", workspace=str(tmp_path))
    result = await certifier.certify()
    assert result.tool_use is False


@pytest.mark.asyncio
async def test_certifier_multi_turn_coherence(tmp_path: Path) -> None:
    """StubProvider that echoes ALPHA-42 in turn 2 yields multi_turn_coherence=True."""
    provider = StubProvider([
        # tool_use scenario (text only, no tools)
        ProviderResponse(content="I cannot list files"),
        # multi_turn scenario
        ProviderResponse(content="Remembered ALPHA-42"),
        ProviderResponse(content="The token is ALPHA-42"),
        # structured_output
        ProviderResponse(content='{"status": "ok"}'),
        # budget
        ProviderResponse(content="Short response"),
    ])
    certifier = ConformanceCertifier(provider=provider, model_id="multi-turn", workspace=str(tmp_path))
    result = await certifier.certify()
    assert result.multi_turn_coherence is True


@pytest.mark.asyncio
async def test_certifier_structured_output(tmp_path: Path) -> None:
    """StubProvider returning valid JSON yields structured_output=True."""
    provider = StubProvider([
        ProviderResponse(content="I cannot list files"),
        ProviderResponse(content="Remembered ALPHA-42"),
        ProviderResponse(content="The token is ALPHA-42"),
        ProviderResponse(content='{"status": "ok"}'),
        ProviderResponse(content="Short response"),
    ])
    certifier = ConformanceCertifier(provider=provider, model_id="json-model", workspace=str(tmp_path))
    result = await certifier.certify()
    assert result.structured_output is True


@pytest.mark.asyncio
async def test_certifier_budget_adherence(tmp_path: Path) -> None:
    """StubProvider completing within budget yields budget_adherence=True."""
    provider = StubProvider([
        ProviderResponse(content="I cannot list files"),
        ProviderResponse(content="Remembered ALPHA-42"),
        ProviderResponse(content="The token is ALPHA-42"),
        ProviderResponse(content='{"status": "ok"}'),
        ProviderResponse(content="Short response"),
    ])
    certifier = ConformanceCertifier(provider=provider, model_id="budget-model", workspace=str(tmp_path))
    result = await certifier.certify()
    assert result.budget_adherence is True


@pytest.mark.asyncio
async def test_cache_hit_skips_recertification(tmp_path: Path) -> None:
    """ConformanceCertifier with use_cache=True returns cached result without calling provider."""
    cache = CertificationCache(cache_dir=tmp_path)
    cached = _make_result(model_id="cached-model")
    cache.save(cached)

    # Provider that would fail if called
    provider = StubProvider([])
    certifier = ConformanceCertifier(provider=provider, model_id="cached-model", workspace=str(tmp_path))
    result = await certifier.certify(cache=cache)
    # Should return cached result without invoking provider
    assert result.model_id == "cached-model"
    assert result.tool_use == cached.tool_use
    # Provider should not have been called
    assert len(provider.calls) == 0


# ---------------------------------------------------------------------------
# warn_stale_certification tests
# ---------------------------------------------------------------------------


def test_stale_warning_printed(capsys: pytest.CaptureFixture) -> None:
    """warn_stale_certification prints to stderr with model_id."""
    warn_stale_certification(model_id="gpt-4o", profile="my-profile")
    captured = capsys.readouterr()
    assert "gpt-4o" in captured.err
    assert captured.out == ""


def test_stale_warning_includes_command(capsys: pytest.CaptureFixture) -> None:
    """Warning text includes the re-certification CLI command."""
    warn_stale_certification(model_id="llama3", profile=None)
    captured = capsys.readouterr()
    assert "python -m agentcouncil.certifier" in captured.err


def test_stale_warning_with_profile_includes_profile(capsys: pytest.CaptureFixture) -> None:
    """When profile is given, the warning includes --profile flag."""
    warn_stale_certification(model_id="llama3", profile="prod")
    captured = capsys.readouterr()
    assert "--profile" in captured.err
    assert "prod" in captured.err


def test_stale_warning_without_profile_includes_model(capsys: pytest.CaptureFixture) -> None:
    """When profile is None, the warning includes --model flag with model_id."""
    warn_stale_certification(model_id="gpt-4", profile=None)
    captured = capsys.readouterr()
    assert "--model" in captured.err
    assert "gpt-4" in captured.err


# ---------------------------------------------------------------------------
# check_certification_gate tests
# ---------------------------------------------------------------------------


def test_uncertified_passes_gate(tmp_path: Path) -> None:
    """check_certification_gate with no cache entry does NOT raise."""
    cache = CertificationCache(cache_dir=tmp_path)
    # Should not raise — uncertified = no block
    check_certification_gate(protocol="review", model_id="unknown-model", profile=None, cache=cache)


def test_gate_blocks_prompt_only_on_review(tmp_path: Path) -> None:
    """check_certification_gate raises ValueError for tool_use=False on 'review'."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="prompt-only", tool_use=False)
    cache.save(result)
    with pytest.raises(ValueError, match="prompt-only"):
        check_certification_gate(protocol="review", model_id="prompt-only", profile=None, cache=cache)


def test_gate_blocks_prompt_only_on_challenge(tmp_path: Path) -> None:
    """check_certification_gate raises ValueError for tool_use=False on 'challenge'."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="no-tools", tool_use=False)
    cache.save(result)
    with pytest.raises(ValueError):
        check_certification_gate(protocol="challenge", model_id="no-tools", profile=None, cache=cache)


def test_gate_allows_tool_capable(tmp_path: Path) -> None:
    """check_certification_gate does NOT raise for tool_use=True."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="capable-model", tool_use=True)
    cache.save(result)
    # Should not raise
    check_certification_gate(protocol="review", model_id="capable-model", profile=None, cache=cache)


def test_gate_allows_brainstorm_even_prompt_only(tmp_path: Path) -> None:
    """check_certification_gate does NOT raise for brainstorm protocol."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="text-only", tool_use=False)
    cache.save(result)
    # brainstorm has no gate
    check_certification_gate(protocol="brainstorm", model_id="text-only", profile=None, cache=cache)


def test_gate_allows_decide_even_prompt_only(tmp_path: Path) -> None:
    """check_certification_gate does NOT raise for decide protocol."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="text-only2", tool_use=False)
    cache.save(result)
    check_certification_gate(protocol="decide", model_id="text-only2", profile=None, cache=cache)


def test_stale_cert_warns_but_passes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """check_certification_gate with version mismatch warns but does not raise."""
    cache = CertificationCache(cache_dir=tmp_path)
    stale = _make_result(model_id="stale-model", tool_use=True, agentcouncil_version="0.0.0-old")
    cache.save(stale)
    # Should not raise but should print a warning
    check_certification_gate(protocol="review", model_id="stale-model", profile=None, cache=cache)
    captured = capsys.readouterr()
    assert "stale-model" in captured.err or "stale" in captured.err.lower()


def test_gate_with_none_cache_passes(tmp_path: Path) -> None:
    """check_certification_gate with cache=None does not raise."""
    # No cache provided — gate cannot check, so passes
    check_certification_gate(protocol="review", model_id="any-model", profile=None, cache=None)


def test_gate_error_message_mentions_protocol(tmp_path: Path) -> None:
    """ValueError from gate includes actionable message about the protocol."""
    cache = CertificationCache(cache_dir=tmp_path)
    result = _make_result(model_id="ponly", tool_use=False)
    cache.save(result)
    with pytest.raises(ValueError) as exc_info:
        check_certification_gate(protocol="review", model_id="ponly", profile=None, cache=cache)
    msg = str(exc_info.value)
    # Should mention the model or protocol in the actionable message
    assert "ponly" in msg or "review" in msg or "function" in msg.lower() or "tool" in msg.lower()


# ---------------------------------------------------------------------------
# Integration tests: server.py gate wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_tool_gate_integrated(monkeypatch: pytest.MonkeyPatch) -> None:
    """review_tool calls check_certification_gate with protocol='review' before proceeding."""
    from agentcouncil.server import review_tool
    gate_calls: list[tuple] = []

    def mock_gate(protocol, *, model_id=None, profile=None, cache=None):
        gate_calls.append((protocol, model_id, profile))

    monkeypatch.setattr("agentcouncil.server.check_certification_gate", mock_gate)

    # Patch _make_provider to raise immediately — ensures gate is checked first
    # (UPROV-03: "nonexistent-profile-xyz" now falls through to CodexProvider; we
    # need an explicit failure to keep the gate-ordering test deterministic)
    monkeypatch.setattr(
        "agentcouncil.server._make_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("stub provider failure")),
    )

    # review_tool will fail downstream (provider stub) but gate should be called first
    with pytest.raises(Exception):
        await review_tool(artifact="test artifact", backend="nonexistent-profile-xyz")

    assert len(gate_calls) == 1
    assert gate_calls[0][0] == "review"


@pytest.mark.asyncio
async def test_challenge_tool_gate_integrated(monkeypatch: pytest.MonkeyPatch) -> None:
    """challenge_tool calls check_certification_gate with protocol='challenge' before proceeding."""
    from agentcouncil.server import challenge_tool
    gate_calls: list[tuple] = []

    def mock_gate(protocol, *, model_id=None, profile=None, cache=None):
        gate_calls.append((protocol, model_id, profile))

    monkeypatch.setattr("agentcouncil.server.check_certification_gate", mock_gate)

    # Patch _make_provider to raise immediately — ensures gate is checked first
    # (UPROV-03: "nonexistent-profile-xyz" now falls through to CodexProvider; we
    # need an explicit failure to keep the gate-ordering test deterministic)
    monkeypatch.setattr(
        "agentcouncil.server._make_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("stub provider failure")),
    )

    # challenge_tool will fail downstream (provider stub) but gate should be called first
    with pytest.raises(Exception):
        await challenge_tool(artifact="test plan", backend="nonexistent-profile-xyz")

    assert len(gate_calls) == 1
    assert gate_calls[0][0] == "challenge"


@pytest.mark.asyncio
async def test_brainstorm_tool_no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """brainstorm_tool does NOT call check_certification_gate."""
    from agentcouncil.server import brainstorm_tool
    gate_calls: list[tuple] = []

    def mock_gate(protocol, *, model_id=None, profile=None, cache=None):
        gate_calls.append((protocol, model_id, profile))

    monkeypatch.setattr("agentcouncil.server.check_certification_gate", mock_gate)

    # Patch _make_provider to raise immediately — ensures failure without real Codex CLI
    # (UPROV-03: "nonexistent-profile-xyz" now dispatches to CodexProvider)
    monkeypatch.setattr(
        "agentcouncil.server._make_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("stub provider failure")),
    )

    # brainstorm_tool will fail downstream but gate should NOT be called
    with pytest.raises(Exception):
        await brainstorm_tool(context="test problem", backend="nonexistent-profile-xyz")

    assert len(gate_calls) == 0


@pytest.mark.asyncio
async def test_decide_tool_no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """decide_tool does NOT call check_certification_gate."""
    from agentcouncil.server import decide_tool
    gate_calls: list[tuple] = []

    def mock_gate(protocol, *, model_id=None, profile=None, cache=None):
        gate_calls.append((protocol, model_id, profile))

    monkeypatch.setattr("agentcouncil.server.check_certification_gate", mock_gate)

    # Patch _make_provider to raise immediately — ensures failure without real Codex CLI
    # (UPROV-03: "nonexistent-profile-xyz" now dispatches to CodexProvider)
    monkeypatch.setattr(
        "agentcouncil.server._make_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("stub provider failure")),
    )

    # decide_tool will fail downstream but gate should NOT be called
    options = [
        {"id": "a", "label": "Option A", "description": "First option"},
        {"id": "b", "label": "Option B", "description": "Second option"},
    ]
    with pytest.raises(Exception):
        await decide_tool(decision="Which option?", options=options, backend="nonexistent-profile-xyz")

    assert len(gate_calls) == 0
