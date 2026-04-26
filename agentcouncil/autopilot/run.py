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
PROJECT_ACTIVE_RUN_REL = Path("docs/autopilot/active-run.json")
PROJECT_RUNS_REL = Path("docs/autopilot/runs")

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


class ProtocolCheckpointEntry(BaseModel):
    """Compact protocol progress event for manual `/autopilot` runs."""

    timestamp: float
    protocol_step: str
    stage: Optional[str] = None
    next_required_action: Optional[str] = None
    required_tool: Optional[str] = None
    blocking_reason: Optional[str] = None
    artifact_refs: dict[str, str] = Field(default_factory=dict)
    note: Optional[str] = None


class AutopilotRun(BaseModel):
    """Durable run state for a single autopilot execution (Section 6.2).

    Uses use_enum_values=True so status is stored and compared as a plain
    string, never as an AutopilotRunStatus member.
    """

    model_config = ConfigDict(use_enum_values=True)

    schema_version: str = "1.1"
    run_id: str
    spec_id: str
    status: AutopilotRunStatus
    current_stage: str
    tier: int
    execution_mode: Literal["runner", "skill"] = "runner"
    review_backend: Optional[str] = None
    challenge_backend: Optional[str] = None
    protocol_step: str = "spec_prep_started"
    next_required_action: Optional[str] = None
    required_tool: Optional[str] = None
    blocking_reason: Optional[str] = None
    resume_prompt: Optional[str] = None
    artifact_refs: dict[str, str] = Field(default_factory=dict)
    workspace_path: Optional[str] = None
    active_state_path: Optional[str] = None
    checkpoint_log: list[ProtocolCheckpointEntry] = Field(default_factory=list)
    tier_promoted_at: Optional[str] = None
    tier_classification_reason: Optional[str] = None
    spec_target_files: list[str] = Field(default_factory=list)
    stages: list[StageCheckpoint]
    artifact_registry: dict[str, dict] = Field(default_factory=dict)
    child_session_ids: list[str] = Field(default_factory=list)
    started_at: float
    updated_at: float
    completed_at: Optional[float] = None
    failure_reason: Optional[str] = None
    build_retry_count: int = 0
    escalation_level: str = "normal"  # "minimal" | "normal" | "verbose"


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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON payload atomically next to the target path."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _project_state_payload(run: AutopilotRun, active: bool = True) -> dict[str, Any]:
    """Return the secret-free project-local guard state for resumed agents."""
    return {
        "schema_version": run.schema_version,
        "active": active,
        "run_id": run.run_id,
        "spec_id": run.spec_id,
        "status": run.status,
        "execution_mode": run.execution_mode,
        "review_backend": run.review_backend,
        "challenge_backend": run.challenge_backend,
        "current_stage": run.current_stage,
        "tier": run.tier,
        "protocol_step": run.protocol_step,
        "next_required_action": run.next_required_action,
        "required_tool": run.required_tool,
        "blocking_reason": run.blocking_reason,
        "resume_prompt": run.resume_prompt,
        "artifact_refs": run.artifact_refs,
        "updated_at": run.updated_at,
    }


def write_project_state(run: AutopilotRun, workspace_path: str | Path, active: bool = True) -> Path:
    """Mirror the active run state into the target project.

    The global run file remains canonical. This project-local mirror is the
    compaction/resume guard that agents can find by reading the repository.
    """
    workspace = Path(workspace_path).expanduser().resolve()
    state_path = workspace / PROJECT_RUNS_REL / run.run_id / "state.json"
    active_path = workspace / PROJECT_ACTIVE_RUN_REL

    payload = _project_state_payload(run, active=active)
    _atomic_write_json(state_path, payload)
    _atomic_write_json(
        active_path,
        {
            "schema_version": run.schema_version,
            "active": active,
            "run_id": run.run_id,
            "state_path": str(state_path),
            "protocol_step": run.protocol_step,
            "review_backend": run.review_backend,
            "challenge_backend": run.challenge_backend,
            "next_required_action": run.next_required_action,
            "required_tool": run.required_tool,
            "updated_at": run.updated_at,
        },
    )
    return state_path


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


_GATED_STEP_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "spec_review_passed": ("awaiting_spec_review", "Cannot record spec review pass before the spec review gate is pending."),
    "awaiting_plan_review": ("spec_review_passed", "Cannot request plan review before the spec review gate passes."),
    "plan_review_passed": ("awaiting_plan_review", "Cannot record plan review pass before the plan review gate is pending."),
    "planning": ("spec_review_passed", "Cannot plan before the spec review gate passes."),
    "building": ("plan_review_passed", "Cannot build before the plan review gate passes."),
    "build_complete": ("plan_review_passed", "Cannot complete build before the plan review gate passes."),
    "build_review_passed": ("build_complete", "Cannot record build review pass before the build is complete."),
    "verifying": ("build_review_passed", "Cannot verify before the build review gate passes."),
    "verify_complete": ("build_review_passed", "Cannot complete verify before the build review gate passes."),
    "challenge_passed": ("verify_complete", "Cannot record challenge pass before verification completes."),
    "challenge_skipped": ("verify_complete", "Cannot skip challenge before verification completes."),
    "awaiting_ship": ("verify_complete", "Cannot ship before verification completes."),
    "shipping": ("verify_complete", "Cannot ship before verification completes."),
    "ship_complete": ("verify_complete", "Cannot complete ship before verification completes."),
}

_TERMINAL_PROTOCOL_STEPS = {"ship_complete", "completed", "failed", "abandoned"}


def _checkpoint_history(run: AutopilotRun) -> set[str]:
    return {entry.protocol_step for entry in run.checkpoint_log} | {run.protocol_step}


def validate_protocol_checkpoint(run: AutopilotRun, next_protocol_step: str) -> None:
    """Validate manual `/autopilot` stage transitions.

    This guard catches the failure mode where an agent finishes build work and
    jumps straight to verify without running the required review_loop gate.
    """
    history = _checkpoint_history(run)
    requirement = _GATED_STEP_REQUIREMENTS.get(next_protocol_step)
    if requirement is not None:
        required_step, message = requirement
        if required_step not in history:
            raise ValueError(f"{message} Required checkpoint: {required_step!r}.")
    if next_protocol_step in {"shipping", "ship_complete"} and run.tier >= 3:
        if "challenge_passed" not in history:
            raise ValueError(
                "Cannot ship a tier 3 autopilot run before the challenge gate passes. "
                "Required checkpoint: 'challenge_passed'."
            )


def checkpoint_run(
    run_id: str,
    *,
    protocol_step: str,
    next_required_action: str | None = None,
    required_tool: str | None = None,
    blocking_reason: str | None = None,
    artifact_refs: dict[str, str] | None = None,
    stage: str | None = None,
    stage_status: Literal["pending", "in_progress", "gated", "advanced", "blocked", "skipped"] | None = None,
    gate_decision: str | None = None,
    revision_guidance: str | None = None,
    note: str | None = None,
    workspace_path: str | Path | None = None,
    execution_mode: Literal["runner", "skill"] = "skill",
    review_backend: str | None = None,
    challenge_backend: str | None = None,
) -> AutopilotRun:
    """Record a durable protocol checkpoint and optionally mirror it locally."""
    now = time.time()
    run = load_run(run_id)
    validate_protocol_checkpoint(run, protocol_step)

    run.schema_version = "1.1"
    run.execution_mode = execution_mode
    if review_backend is not None:
        run.review_backend = review_backend
    if challenge_backend is not None:
        run.challenge_backend = challenge_backend
    run.protocol_step = protocol_step
    run.next_required_action = next_required_action
    run.required_tool = required_tool
    run.blocking_reason = blocking_reason
    run.current_stage = stage or run.current_stage
    run.updated_at = now
    if artifact_refs:
        run.artifact_refs.update(artifact_refs)
    run.resume_prompt = build_resume_prompt(run)

    if stage:
        checkpoint = next((s for s in run.stages if s.stage_name == stage), None)
        if checkpoint is None:
            checkpoint = StageCheckpoint(stage_name=stage, status=stage_status or "pending")
            run.stages.append(checkpoint)
        if stage_status:
            checkpoint.status = stage_status
        if gate_decision:
            checkpoint.gate_decision = gate_decision
        if revision_guidance:
            checkpoint.revision_guidance = revision_guidance
        if stage_status == "in_progress" and checkpoint.started_at is None:
            checkpoint.started_at = now
        if stage_status in {"advanced", "blocked", "skipped"}:
            checkpoint.completed_at = now

    run.checkpoint_log.append(
        ProtocolCheckpointEntry(
            timestamp=now,
            protocol_step=protocol_step,
            stage=stage,
            next_required_action=next_required_action,
            required_tool=required_tool,
            blocking_reason=blocking_reason,
            artifact_refs=artifact_refs or {},
            note=note,
        )
    )

    active = protocol_step not in _TERMINAL_PROTOCOL_STEPS and run.status not in {"completed", "failed"}
    if protocol_step in {"failed", "abandoned"} and run.status == "running":
        run.status = "failed"
        run.failure_reason = blocking_reason or note or protocol_step
    if protocol_step in {"ship_complete", "completed"}:
        run.status = "completed"
        run.completed_at = now

    state_path: Path | None = None
    if workspace_path:
        state_path = write_project_state(run, workspace_path, active=active)
        run.workspace_path = str(Path(workspace_path).expanduser().resolve())
        run.active_state_path = str(state_path)
        run.resume_prompt = build_resume_prompt(run)

    persist(run)
    return run


def build_resume_prompt(run: AutopilotRun) -> str:
    """Compact instruction suitable for context-compaction summaries."""
    action = run.next_required_action or "Continue from the recorded protocol step."
    tool = f" Required tool: {run.required_tool}." if run.required_tool else ""
    blocker = f" Blocked: {run.blocking_reason}." if run.blocking_reason else ""
    return (
        f"Autopilot run {run.run_id} is at {run.protocol_step} "
        f"(stage: {run.current_stage}). {action}.{tool}{blocker} "
        "Read docs/autopilot/active-run.json before doing any further work."
    )


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
    "ProtocolCheckpointEntry",
    "AutopilotRun",
    "RUN_DIR",
    "PROJECT_ACTIVE_RUN_REL",
    "PROJECT_RUNS_REL",
    "persist",
    "load_run",
    "checkpoint_run",
    "validate_protocol_checkpoint",
    "write_project_state",
    "build_resume_prompt",
    "validate_transition",
    "resume",
]
