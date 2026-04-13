from __future__ import annotations

import json

import pytest
from pydantic import ValidationError


def _make_artifact(**overrides):
    """Helper: build a valid ConsensusArtifact with defaults, overriding as needed."""
    from agentcouncil.schemas import ConsensusArtifact, ConsensusStatus

    defaults = {
        "recommended_direction": "Use approach A",
        "agreement_points": ["Both agents prefer A"],
        "disagreement_points": [],
        "rejected_alternatives": ["Approach B — too complex"],
        "open_risks": ["Untested at scale"],
        "next_action": "Prototype A",
        "status": ConsensusStatus.consensus,
    }
    defaults.update(overrides)
    return ConsensusArtifact(**defaults)


def test_import_clean():
    from agentcouncil.schemas import ConsensusArtifact, ConsensusStatus
    assert ConsensusArtifact is not None
    assert ConsensusStatus is not None


def test_all_fields_present():
    from agentcouncil.schemas import ConsensusArtifact
    field_names = set(ConsensusArtifact.model_fields.keys())
    expected = {
        "recommended_direction",
        "agreement_points",
        "disagreement_points",
        "rejected_alternatives",
        "open_risks",
        "next_action",
        "status",
    }
    assert field_names == expected


def test_status_enum_values():
    from agentcouncil.schemas import ConsensusStatus
    values = [member.value for member in ConsensusStatus]
    assert sorted(values) == sorted([
        "consensus",
        "consensus_with_reservations",
        "unresolved_disagreement",
        "partial_failure",
    ])
    assert len(ConsensusStatus) == 4


def test_status_serializes_as_string():
    artifact = _make_artifact()
    dumped = artifact.model_dump()
    assert isinstance(dumped["status"], str)
    assert dumped["status"] == "consensus"


def test_json_roundtrip():
    original = _make_artifact()
    json_str = original.model_dump_json()
    restored = type(original).model_validate_json(json_str)
    assert restored.model_dump() == original.model_dump()


def test_all_fields_required():
    from agentcouncil.schemas import ConsensusArtifact
    required_fields = [
        "recommended_direction",
        "agreement_points",
        "disagreement_points",
        "rejected_alternatives",
        "open_risks",
        "next_action",
        "status",
    ]
    for field in required_fields:
        data = _make_artifact().model_dump()
        del data[field]
        with pytest.raises(ValidationError):
            ConsensusArtifact(**data)


def test_model_json_schema():
    from agentcouncil.schemas import ConsensusArtifact
    schema = ConsensusArtifact.model_json_schema()
    props = set(schema["properties"].keys())
    expected = {
        "recommended_direction",
        "agreement_points",
        "disagreement_points",
        "rejected_alternatives",
        "open_risks",
        "next_action",
        "status",
    }
    assert props == expected
    # Enum values present in $defs
    defs = schema.get("$defs", {})
    status_def = defs.get("ConsensusStatus", {})
    assert set(status_def.get("enum", [])) == {
        "consensus",
        "consensus_with_reservations",
        "unresolved_disagreement",
        "partial_failure",
    }


def test_partial_failure_status_validates():
    from agentcouncil.schemas import ConsensusArtifact
    artifact = ConsensusArtifact(
        recommended_direction="fallback direction",
        agreement_points=[],
        disagreement_points=[],
        rejected_alternatives=[],
        open_risks=["partial failure — one agent did not respond"],
        next_action="retry",
        status="partial_failure",
    )
    assert artifact.model_dump()["status"] == "partial_failure"


# ---------------------------------------------------------------------------
# TranscriptMeta new fields (Plan 12-02)
# ---------------------------------------------------------------------------


def test_transcript_meta_has_new_fields():
    """TranscriptMeta can be constructed with the 4 new Optional[str] fields."""
    from agentcouncil.schemas import TranscriptMeta

    meta = TranscriptMeta(
        outside_provider="stub",
        outside_profile="local-dev",
        outside_session_mode="replay",
        outside_workspace_access="assisted",
    )
    assert meta.outside_provider == "stub"
    assert meta.outside_profile == "local-dev"
    assert meta.outside_session_mode == "replay"
    assert meta.outside_workspace_access == "assisted"


def test_transcript_meta_backward_compat():
    """TranscriptMeta() with no args still works — all fields default to None."""
    from agentcouncil.schemas import TranscriptMeta

    meta = TranscriptMeta()
    assert meta.outside_provider is None
    assert meta.outside_profile is None
    assert meta.outside_session_mode is None
    assert meta.outside_workspace_access is None
    # Existing fields still work
    assert meta.lead_backend is None
    assert meta.outside_model is None


def test_transcript_meta_partial_construction():
    """TranscriptMeta with only some new fields — others default to None."""
    from agentcouncil.schemas import TranscriptMeta

    meta = TranscriptMeta(outside_provider="ollama", outside_model="llama3")
    assert meta.outside_provider == "ollama"
    assert meta.outside_model == "llama3"
    assert meta.outside_profile is None
    assert meta.outside_session_mode is None
    assert meta.outside_workspace_access is None
