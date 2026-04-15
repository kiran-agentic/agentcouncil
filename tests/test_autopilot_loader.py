"""Tests for agentcouncil.autopilot.loader.

Covers ORCH-01 (StageManifest schema validation) and ORCH-02 (ManifestLoader
discovery, cross-manifest validation, registry construction).
"""
from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from agentcouncil.autopilot.loader import (
    KNOWN_ARTIFACT_TYPES,
    ManifestLoader,
    SourceProvenance,
    StageManifest,
    StageRegistryEntry,
    load_default_registry,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_valid_manifest(**overrides) -> dict:
    """Return a valid manifest dict using plan stage defaults."""
    defaults = {
        "stage_name": "plan",
        "version": "1.0",
        "stage_type": "work",
        "input_artifact": "SpecPrepArtifact",
        "output_artifact": "PlanArtifact",
        "default_gate": "review_loop",
        "side_effect_level": "none",
        "retry_policy": "once",
        "approval_required": False,
        "allowed_next": ["build"],
    }
    defaults.update(overrides)
    return defaults


def _write_manifest(tmp_path, stage_name: str, manifest_dict: dict) -> None:
    """Create {tmp_path}/{stage_name}/manifest.yaml using yaml.dump."""
    stage_dir = tmp_path / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = stage_dir / "manifest.yaml"
    manifest_file.write_text(yaml.dump(manifest_dict), encoding="utf-8")


# ---------------------------------------------------------------------------
# ORCH-01: StageManifest schema tests
# ---------------------------------------------------------------------------


def test_stage_manifest_valid():
    """StageManifest with all valid fields constructs successfully."""
    m = StageManifest(**_make_valid_manifest())
    assert m.stage_name == "plan"
    assert m.version == "1.0"
    assert m.stage_type == "work"
    assert m.input_artifact == "SpecPrepArtifact"
    assert m.output_artifact == "PlanArtifact"
    assert m.default_gate == "review_loop"
    assert m.side_effect_level == "none"
    assert m.retry_policy == "once"
    assert m.approval_required is False
    assert m.allowed_next == ["build"]
    assert m.source_provenance is None


def test_stage_manifest_null_input():
    """input_artifact=None (spec_prep entry-point case) constructs successfully."""
    m = StageManifest(**_make_valid_manifest(
        stage_name="spec_prep",
        input_artifact=None,
        output_artifact="SpecPrepArtifact",
        default_gate="none",
        retry_policy="none",
        allowed_next=["plan"],
    ))
    assert m.input_artifact is None
    assert m.stage_name == "spec_prep"


def test_stage_manifest_unknown_input_artifact():
    """input_artifact with an unknown type raises ValidationError."""
    with pytest.raises(ValidationError, match="not a known artifact type"):
        StageManifest(**_make_valid_manifest(input_artifact="FakeType"))


def test_stage_manifest_unknown_output_artifact():
    """output_artifact with an unknown type raises ValidationError."""
    with pytest.raises(ValidationError, match="not a known artifact type"):
        StageManifest(**_make_valid_manifest(output_artifact="FakeType"))


def test_stage_manifest_invalid_stage_type():
    """stage_type with an invalid Literal value raises ValidationError."""
    with pytest.raises(ValidationError):
        StageManifest(**_make_valid_manifest(stage_type="invalid"))


def test_stage_manifest_invalid_gate():
    """default_gate with an invalid Literal value raises ValidationError."""
    with pytest.raises(ValidationError):
        StageManifest(**_make_valid_manifest(default_gate="invalid"))


def test_stage_manifest_invalid_side_effect():
    """side_effect_level with an invalid Literal value raises ValidationError."""
    with pytest.raises(ValidationError):
        StageManifest(**_make_valid_manifest(side_effect_level="extreme"))


def test_stage_manifest_invalid_retry():
    """retry_policy with an invalid Literal value raises ValidationError."""
    with pytest.raises(ValidationError):
        StageManifest(**_make_valid_manifest(retry_policy="always"))


def test_source_provenance():
    """SourceProvenance constructs with all required fields."""
    sp = SourceProvenance(
        repo="https://github.com/example/repo",
        path="workflows/plan/workflow.md",
        license="MIT",
        commit="abc1234",
        date_copied="2026-04-15",
    )
    assert sp.repo == "https://github.com/example/repo"
    assert sp.path == "workflows/plan/workflow.md"
    assert sp.license == "MIT"
    assert sp.commit == "abc1234"
    assert sp.date_copied == "2026-04-15"
    assert sp.modified is False  # default


def test_source_provenance_modified_flag():
    """SourceProvenance modified field can be set to True."""
    sp = SourceProvenance(
        repo="https://github.com/example/repo",
        path="workflows/plan/workflow.md",
        license="MIT",
        commit="abc1234",
        date_copied="2026-04-15",
        modified=True,
    )
    assert sp.modified is True


def test_stage_manifest_with_provenance():
    """StageManifest with optional source_provenance sub-model constructs."""
    provenance = {
        "repo": "https://github.com/example/skills",
        "path": "plan/workflow.md",
        "license": "MIT",
        "commit": "deadbeef",
        "date_copied": "2026-04-15",
    }
    m = StageManifest(**_make_valid_manifest(source_provenance=provenance))
    assert m.source_provenance is not None
    assert m.source_provenance.license == "MIT"


def test_known_artifact_types_count():
    """KNOWN_ARTIFACT_TYPES has exactly 7 artifact type names."""
    assert len(KNOWN_ARTIFACT_TYPES) == 7


def test_known_artifact_types_contents():
    """KNOWN_ARTIFACT_TYPES contains all expected artifact names."""
    expected = {
        "SpecArtifact", "SpecPrepArtifact", "PlanArtifact",
        "BuildArtifact", "VerifyArtifact", "ShipArtifact", "GateDecision",
    }
    assert KNOWN_ARTIFACT_TYPES == expected


# ---------------------------------------------------------------------------
# ORCH-02: ManifestLoader unit tests (using tmp_path)
# ---------------------------------------------------------------------------


def test_loader_discovers_all_stages(tmp_path):
    """ManifestLoader on a tmp dir with 3 valid manifests returns 3 entries."""
    _write_manifest(tmp_path, "spec_prep", _make_valid_manifest(
        stage_name="spec_prep",
        input_artifact=None,
        output_artifact="SpecPrepArtifact",
        default_gate="none",
        retry_policy="none",
        allowed_next=["plan"],
    ))
    _write_manifest(tmp_path, "plan", _make_valid_manifest(
        stage_name="plan",
        allowed_next=["build"],
    ))
    _write_manifest(tmp_path, "build", _make_valid_manifest(
        stage_name="build",
        input_artifact="PlanArtifact",
        output_artifact="BuildArtifact",
        default_gate="review_loop",
        side_effect_level="local",
        allowed_next=[],
    ))

    loader = ManifestLoader(tmp_path)
    registry = loader.load()

    assert len(registry) == 3
    assert set(registry.keys()) == {"spec_prep", "plan", "build"}


def test_loader_rejects_unknown_artifact(tmp_path):
    """Manifest with output_artifact='FakeType' causes loader to raise ValueError."""
    bad_manifest = _make_valid_manifest(
        stage_name="broken",
        input_artifact=None,
        output_artifact="FakeType",
        allowed_next=[],
    )
    _write_manifest(tmp_path, "broken", bad_manifest)

    loader = ManifestLoader(tmp_path)
    with pytest.raises((ValueError, ValidationError)):
        loader.load()


def test_loader_rejects_unknown_allowed_next(tmp_path):
    """Manifest with allowed_next=['nonexistent'] raises ValueError with 'unknown stage'."""
    _write_manifest(tmp_path, "plan", _make_valid_manifest(
        stage_name="plan",
        allowed_next=["nonexistent"],
    ))

    loader = ManifestLoader(tmp_path)
    with pytest.raises(ValueError, match="unknown stage"):
        loader.load()


def test_registry_entry_has_workflow_content(tmp_path):
    """StageRegistryEntry.workflow_content contains the workflow.md text."""
    stage_dir = tmp_path / "plan"
    stage_dir.mkdir()
    manifest_file = stage_dir / "manifest.yaml"
    manifest_file.write_text(yaml.dump(_make_valid_manifest(
        stage_name="plan",
        allowed_next=[],
    )), encoding="utf-8")
    workflow_file = stage_dir / "workflow.md"
    workflow_file.write_text("# Plan Workflow\n\nReal content here.", encoding="utf-8")

    loader = ManifestLoader(tmp_path)
    registry = loader.load()

    assert "plan" in registry
    assert "Real content here." in registry["plan"].workflow_content


def test_registry_entry_empty_workflow_content(tmp_path):
    """Missing workflow.md yields empty string for workflow_content."""
    _write_manifest(tmp_path, "plan", _make_valid_manifest(
        stage_name="plan",
        allowed_next=[],
    ))
    # No workflow.md created

    loader = ManifestLoader(tmp_path)
    registry = loader.load()

    assert "plan" in registry
    assert registry["plan"].workflow_content == ""


def test_loader_missing_directory():
    """ManifestLoader on a nonexistent path raises FileNotFoundError."""
    from pathlib import Path

    loader = ManifestLoader(Path("/tmp/nonexistent_path_xyz_abc_123"))
    with pytest.raises(FileNotFoundError):
        loader.load()


def test_stage_registry_entry_is_frozen(tmp_path):
    """StageRegistryEntry is frozen (immutable dataclass)."""
    _write_manifest(tmp_path, "plan", _make_valid_manifest(
        stage_name="plan",
        allowed_next=[],
    ))
    loader = ManifestLoader(tmp_path)
    registry = loader.load()
    entry = registry["plan"]

    with pytest.raises((AttributeError, TypeError)):
        entry.workflow_content = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration tests: real manifest files
# ---------------------------------------------------------------------------


def test_default_registry_loads():
    """load_default_registry() returns 5 entries with correct stage names."""
    registry = load_default_registry()
    assert len(registry) == 5
    assert set(registry.keys()) == {"spec_prep", "plan", "build", "verify", "ship"}


def test_default_registry_entry_types():
    """Each entry in the default registry is a StageRegistryEntry."""
    registry = load_default_registry()
    for stage_name, entry in registry.items():
        assert isinstance(entry, StageRegistryEntry), (
            f"Entry for '{stage_name}' is not a StageRegistryEntry"
        )
        assert isinstance(entry.manifest, StageManifest), (
            f"Entry for '{stage_name}' does not have a StageManifest"
        )


def test_default_registry_has_workflow_content():
    """All five default stages have non-empty workflow_content."""
    registry = load_default_registry()
    for stage_name, entry in registry.items():
        assert entry.workflow_content, (
            f"Stage '{stage_name}' has empty workflow_content"
        )


def test_default_registry_pipeline_chain():
    """Pipeline chain: spec_prep->plan->build->verify->ship->[]."""
    registry = load_default_registry()

    assert registry["spec_prep"].manifest.allowed_next == ["plan"]
    assert registry["plan"].manifest.allowed_next == ["build"]
    assert registry["build"].manifest.allowed_next == ["verify"]
    assert registry["verify"].manifest.allowed_next == ["ship"]
    assert registry["ship"].manifest.allowed_next == []


def test_default_registry_spec_prep_has_null_input():
    """spec_prep stage has input_artifact=None (entry-point stage)."""
    registry = load_default_registry()
    assert registry["spec_prep"].manifest.input_artifact is None


def test_default_registry_verify_gate_is_challenge():
    """verify stage has default_gate=challenge."""
    registry = load_default_registry()
    assert registry["verify"].manifest.default_gate == "challenge"


def test_default_registry_build_has_local_side_effects():
    """build and verify stages have side_effect_level=local."""
    registry = load_default_registry()
    assert registry["build"].manifest.side_effect_level == "local"
    assert registry["verify"].manifest.side_effect_level == "local"


def test_default_registry_ship_is_terminal():
    """ship stage is the terminal stage with empty allowed_next."""
    registry = load_default_registry()
    assert registry["ship"].manifest.allowed_next == []


def test_default_registry_stage_types_are_work():
    """All five default stages have stage_type=work."""
    registry = load_default_registry()
    for stage_name, entry in registry.items():
        assert entry.manifest.stage_type == "work", (
            f"Stage '{stage_name}' has unexpected stage_type: {entry.manifest.stage_type}"
        )
