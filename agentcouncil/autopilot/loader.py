"""Manifest schema model, loader, and stage registry for Autopilot workflows.

This module implements the stage-contract layer that sits between Phase 26's
artifact models and the linear orchestrator. It discovers all manifest.yaml
files under the workflows/ directory, validates them at startup, and builds a
typed StageRegistry that the orchestrator can use without hardcoded stage
knowledge.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, model_validator

__all__ = [
    "StageManifest",
    "SourceProvenance",
    "StageRegistryEntry",
    "ManifestLoader",
    "load_default_registry",
    "KNOWN_ARTIFACT_TYPES",
]

# Artifact type names from artifacts.py __all__ that manifests may reference.
# Using a string constant avoids circular imports — the loader validates names,
# not class instances.
KNOWN_ARTIFACT_TYPES: frozenset[str] = frozenset({
    "SpecArtifact",
    "SpecPrepArtifact",
    "PlanArtifact",
    "BuildArtifact",
    "VerifyArtifact",
    "ShipArtifact",
    "GateDecision",
})


class SourceProvenance(BaseModel):
    """Attribution block for vendored workflow content."""

    repo: str
    path: str
    license: str
    commit: str
    date_copied: str
    modified: bool = False


class StageManifest(BaseModel):
    """Parsed representation of a manifest.yaml file.

    Every workflow directory must contain a manifest.yaml that conforms to
    this schema. The loader validates all fields at startup.
    """

    stage_name: str
    version: str
    stage_type: Literal["work", "gate"]
    input_artifact: Optional[str] = None
    output_artifact: str
    default_gate: Literal["brainstorm", "review", "review_loop", "challenge", "none"]
    side_effect_level: Literal["none", "local", "external"]
    retry_policy: Literal["none", "once", "backend_fallback"]
    approval_required: bool
    allowed_next: list[str]
    source_provenance: Optional[SourceProvenance] = None

    @model_validator(mode="after")
    def check_artifact_types(self) -> "StageManifest":
        """Validate input/output artifact names against KNOWN_ARTIFACT_TYPES."""
        if self.input_artifact is not None:
            if self.input_artifact not in KNOWN_ARTIFACT_TYPES:
                raise ValueError(
                    f"input_artifact '{self.input_artifact}' is not a known artifact type. "
                    f"Known types: {sorted(KNOWN_ARTIFACT_TYPES)}"
                )
        if self.output_artifact not in KNOWN_ARTIFACT_TYPES:
            raise ValueError(
                f"output_artifact '{self.output_artifact}' is not a known artifact type. "
                f"Known types: {sorted(KNOWN_ARTIFACT_TYPES)}"
            )
        return self


@dataclass(frozen=True)
class StageRegistryEntry:
    """Registry entry holding both the parsed manifest and workflow content."""

    manifest: StageManifest
    workflow_content: str  # full text of workflow.md; empty string if file absent


class ManifestLoader:
    """Discovers and validates all manifest.yaml files under a workflows root.

    Uses a two-pass approach:
    - Pass 1: Parse each manifest.yaml independently (Pydantic validates fields
      and artifact type names).
    - Pass 2: Cross-validate all allowed_next references against the complete
      set of discovered stage names. This catches misconfigurations at startup.
    """

    def __init__(self, workflows_root: Path) -> None:
        self._root = workflows_root

    def load(self) -> dict[str, StageRegistryEntry]:
        """Load all manifests and return a registry keyed by stage_name.

        Raises:
            FileNotFoundError: If workflows_root does not exist or is not a
                directory.
            ValueError: If a manifest references an unknown artifact type or an
                unknown stage in allowed_next.
            pydantic.ValidationError: If a manifest is missing required fields
                or contains invalid Literal values.
        """
        if not self._root.is_dir():
            raise FileNotFoundError(
                f"Workflows directory not found: {self._root}"
            )

        entries: dict[str, StageRegistryEntry] = {}

        # Pass 1: parse each manifest independently
        for manifest_path in sorted(self._root.glob("*/manifest.yaml")):
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(
                    f"Manifest at {manifest_path} did not parse as a YAML mapping"
                )
            manifest = StageManifest(**raw)
            workflow_path = manifest_path.parent / "workflow.md"
            content = (
                workflow_path.read_text(encoding="utf-8")
                if workflow_path.exists()
                else ""
            )
            entries[manifest.stage_name] = StageRegistryEntry(manifest, content)

        # Pass 2: cross-manifest allowed_next validation
        known_stages = set(entries.keys())
        for stage_name, entry in entries.items():
            for next_stage in entry.manifest.allowed_next:
                if next_stage not in known_stages:
                    raise ValueError(
                        f"Stage '{stage_name}': allowed_next references unknown "
                        f"stage '{next_stage}'. Known stages: {sorted(known_stages)}"
                    )

        return entries


def load_default_registry() -> dict[str, StageRegistryEntry]:
    """Load the stage registry from the package-relative workflows/ directory.

    This convenience function resolves the workflows/ path relative to
    loader.py's own location, ensuring it works regardless of the current
    working directory.
    """
    workflows_root = Path(__file__).parent / "workflows"
    return ManifestLoader(workflows_root).load()
