"""agentcouncil.autopilot.run — AutopilotRun state model, persistence, and resume.

Implements the durable run state layer described in Section 6 of
docs/AUTOPILOT-ROADMAP.md. Provides:

- AutopilotRunStatus: five-state enum for run lifecycle
- StageCheckpoint: per-stage snapshot with artifact serialization
- AutopilotRun: full run model (schema version 1.0)
- persist(): atomic write to ~/.agentcouncil/autopilot/{run_id}.json
- load_run(): deserialize from disk with path traversal protection
- validate_transition(): enforce state machine (PERS-01)
- resume(): reconstruct artifact registry from paused runs (PERS-02)
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agentcouncil.autopilot.artifacts import (
    BuildArtifact,
    PlanArtifact,
    ShipArtifact,
    SpecPrepArtifact,
    VerifyArtifact,
)

# ---------------------------------------------------------------------------
# Directory and path safety
# ---------------------------------------------------------------------------

RUN_DIR = Path.home() / ".agentcouncil" / "autopilot"

# R-03: run_id validation — reject path traversal attempts (mirrors journal.py)
_SAFE_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

# ---------------------------------------------------------------------------
# Stage artifact class mapping (for registry reconstruction on resume)
# ---------------------------------------------------------------------------

_STAGE_ARTIFACT_CLASS: dict[str, type] = {
    "spec_prep": SpecPrepArtifact,
    "plan": PlanArtifact,
    "build": BuildArtifact,
    "verify": VerifyArtifact,
    "ship": ShipArtifact,
}


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class AutopilotRunStatus(str, Enum):
    """Five-state lifecycle enum for an autopilot run (Section 6.1)."""

    running = "running"
    paused_for_approval = "paused_for_approval"
    paused_for_revision = "paused_for_revision"
    completed = "completed"
    failed = "failed"


class StageCheckpoint(BaseModel):
    """Per-stage snapshot persisted at each state transition (Section 6.2)."""

    stage_name: str
    status: Literal["pending", "in_progress", "gated", "advanced", "blocked", "skipped"]
    artifact_snapshot: Optional[dict] = None
    gate_session_id: Optional[str] = None
    gate_decision: Optional[str] = None
    revision_guidance: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class AutopilotRun(BaseModel):
    """Durable run state for a single autopilot execution (Section 6.2).

    Uses use_enum_values=True so status is stored and compared as a plain
    string, never as an AutopilotRunStatus member.
    """

    model_config = ConfigDict(use_enum_values=True)

    schema_version: str = "1.0"
    run_id: str
    spec_id: str
    status: AutopilotRunStatus
    current_stage: str
    tier: int
    tier_promoted_at: Optional[str] = None
    stages: list[StageCheckpoint]
    artifact_registry: dict[str, dict] = Field(default_factory=dict)
    child_session_ids: list[str] = Field(default_factory=list)
    started_at: float
    updated_at: float
    completed_at: Optional[float] = None
    failure_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_run_id(run_id: str) -> None:
    """Reject run_ids that could escape the run directory.

    Uses regex as the primary guard, then a belt-and-suspenders resolved
    path check to prevent any OS-level path traversal tricks.
    """
    if not run_id or not _SAFE_RUN_ID_RE.match(run_id):
        raise ValueError(
            f"invalid run_id: {run_id!r} — "
            "must contain only alphanumeric, hyphen, or underscore characters"
        )
    # Belt-and-suspenders: verify resolved path stays under RUN_DIR
    resolved = (RUN_DIR / f"{run_id}.json").resolve()
    run_dir_resolved = RUN_DIR.resolve()
    if not str(resolved).startswith(str(run_dir_resolved)):
        raise ValueError(f"run_id would escape run directory: {run_id!r}")


def _ensure_dir() -> None:
    """Create run directory if it doesn't exist (lazy creation)."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Persistence: PERS-01
# ---------------------------------------------------------------------------


def persist(run: AutopilotRun) -> Path:
    """Persist a run to disk atomically (PERS-01).

    Writes to a temp file in RUN_DIR (same filesystem), then renames via
    os.replace() to prevent partial files on crash. Mirrors journal.py pattern.

    Args:
        run: AutopilotRun instance to persist.

    Returns:
        Path to the written JSON file.
    """
    _validate_run_id(run.run_id)
    _ensure_dir()
    target = RUN_DIR / f"{run.run_id}.json"
    data = run.model_dump_json(indent=2)

    # Atomic write: temp file on same filesystem, then os.replace (PERS-01)
    fd, tmp_path = tempfile.mkstemp(dir=RUN_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp_path, target)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return target


def load_run(run_id: str) -> AutopilotRun:
    """Load a run from disk by run_id (PERS-01).

    Args:
        run_id: Identifier of the run to load.

    Returns:
        Deserialized AutopilotRun.

    Raises:
        ValueError: If run_id is invalid (path traversal protection).
        FileNotFoundError: If the run file does not exist.
    """
    _validate_run_id(run_id)
    target = RUN_DIR / f"{run_id}.json"
    if not target.exists():
        raise FileNotFoundError(f"run not found: {run_id!r}")
    data = target.read_text()
    return AutopilotRun.model_validate_json(data)


# ---------------------------------------------------------------------------
# State machine: validate_transition
# ---------------------------------------------------------------------------

# Only "running" has outgoing transitions; all terminal/paused states are sinks.
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "running": {"paused_for_approval", "paused_for_revision", "completed", "failed"},
    "paused_for_approval": set(),
    "paused_for_revision": set(),
    "completed": set(),
    "failed": set(),
}


def validate_transition(current_status: str, next_status: str) -> None:
    """Enforce the state machine transition rules (PERS-01).

    Args:
        current_status: Current run status as string literal.
        next_status: Requested next status as string literal.

    Raises:
        ValueError: If the transition is not permitted.
    """
    allowed = _VALID_TRANSITIONS.get(current_status, set())
    if next_status not in allowed:
        raise ValueError(
            f"invalid status transition: {current_status!r} -> {next_status!r}. "
            f"Allowed from {current_status!r}: {sorted(allowed) or '(none)'}"
        )


# ---------------------------------------------------------------------------
# Resume: PERS-02
# ---------------------------------------------------------------------------


def resume(run_id: str) -> tuple[AutopilotRun, dict[str, Any]]:
    """Resume from a paused run, reconstructing the artifact registry (PERS-02).

    Only "paused_for_approval" and "paused_for_revision" runs can be resumed.
    Iterates stage checkpoints and deserializes artifact_snapshot dicts into
    typed artifact instances using _STAGE_ARTIFACT_CLASS.

    Args:
        run_id: Identifier of the run to resume.

    Returns:
        A (run, registry) tuple where registry maps stage_name -> typed artifact.

    Raises:
        FileNotFoundError: If the run file does not exist.
        ValueError: If the run is in "failed", "running", or "completed" state.
    """
    run = load_run(run_id)

    # Status comparisons use STRING LITERALS (not enum members) because
    # AutopilotRun uses use_enum_values=True
    if run.status == "failed":
        raise ValueError(
            f"cannot resume a failed run: {run_id!r}. "
            f"Failure reason: {run.failure_reason}"
        )
    if run.status == "running":
        raise ValueError(
            f"cannot resume a running run: {run_id!r}. "
            "Run is currently active — stop it before resuming."
        )
    if run.status == "completed":
        raise ValueError(
            f"cannot resume a completed run: {run_id!r}. "
            "Run has already finished successfully."
        )

    # Only paused_for_approval or paused_for_revision reach here
    registry: dict[str, Any] = {}
    for checkpoint in run.stages:
        if checkpoint.artifact_snapshot is not None:
            stage = checkpoint.stage_name
            artifact_cls = _STAGE_ARTIFACT_CLASS.get(stage)
            if artifact_cls is not None:
                registry[stage] = artifact_cls.model_validate(checkpoint.artifact_snapshot)

    return run, registry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "AutopilotRunStatus",
    "StageCheckpoint",
    "AutopilotRun",
    "RUN_DIR",
    "persist",
    "load_run",
    "validate_transition",
    "resume",
]
