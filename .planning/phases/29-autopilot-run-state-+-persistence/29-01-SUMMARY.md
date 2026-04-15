---
phase: 29-autopilot-run-state-+-persistence
plan: 01
subsystem: autopilot
tags: [pydantic, persistence, state-machine, atomic-writes, json, python]

# Dependency graph
requires:
  - phase: 26-artifact-schemas
    provides: SpecPrepArtifact, PlanArtifact, BuildArtifact, VerifyArtifact, ShipArtifact used in _STAGE_ARTIFACT_CLASS mapping
  - phase: 28-gate-normalization-layer
    provides: GateNormalizer — gate output feeds into run status transitions

provides:
  - AutopilotRunStatus enum (5 states: running, paused_for_approval, paused_for_revision, completed, failed)
  - StageCheckpoint model with 8 fields for per-stage artifact snapshots
  - AutopilotRun durable state model (schema v1.0, use_enum_values=True)
  - persist() atomic write to ~/.agentcouncil/autopilot/{run_id}.json
  - load_run() deserialize with path traversal protection
  - validate_transition() state machine enforcement (running -> terminal/paused only)
  - resume() reconstruct typed artifact registry from paused run checkpoints

affects:
  - 30-orchestrator (uses AutopilotRun for durable state, persist/load_run after every transition, resume on startup)
  - 31-workflows (orchestrator persists run state during stage execution)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomic writes via tempfile.mkstemp(dir=RUN_DIR) + os.replace — same filesystem, no partial files on crash"
    - "use_enum_values=True in model_config — status always a string literal, never an enum member"
    - "Path traversal guard: regex + resolved path startswith check (mirrors journal.py)"
    - "Resume as pure function returning (run, registry) tuple — no mutation"
    - "Stage artifact class mapping for registry reconstruction from dict snapshots"

key-files:
  created:
    - agentcouncil/autopilot/run.py
    - tests/test_autopilot_run.py
  modified:
    - agentcouncil/autopilot/__init__.py

key-decisions:
  - "Status comparisons use string literals not enum members due to use_enum_values=True"
  - "resume() is a pure function — returns (run, registry) tuple, does not mutate run or write to disk"
  - "validate_transition() uses string-keyed dict — all paused/terminal statuses map to empty set (no outgoing transitions)"
  - "_validate_run_id uses both regex AND resolved path check for belt-and-suspenders path traversal protection"

patterns-established:
  - "Atomic write pattern: tempfile.mkstemp(dir=target_dir, suffix='.tmp') + os.replace (copied from journal.py)"
  - "Run ID validation: _SAFE_RUN_ID_RE.match + resolved path startswith guard"
  - "TDD commit sequence: test(failing) -> feat(implementation) for each module"

requirements-completed: [PERS-01, PERS-02]

# Metrics
duration: 15min
completed: 2026-04-15
---

# Phase 29 Plan 01: AutopilotRun State Summary

**Durable run state model with atomic JSON persistence, state machine enforcement, and paused-run resume with typed artifact registry reconstruction**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-15T08:00:00Z
- **Completed:** 2026-04-15T08:15:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Implemented `AutopilotRun` (14-field Pydantic model, schema v1.0) and `StageCheckpoint` (8-field model) matching Section 6.2 of AUTOPILOT-ROADMAP.md
- Built atomic persistence (`persist()`) using `tempfile.mkstemp(dir=RUN_DIR)` + `os.replace()` — crash-safe, no partial files
- Implemented `resume()` that reconstructs typed artifact instances (`SpecPrepArtifact`, `PlanArtifact`, etc.) from stored dict snapshots via `_STAGE_ARTIFACT_CLASS` mapping
- State machine (`validate_transition()`) enforces `running` as the only state with outgoing transitions; all paused and terminal states are sinks
- Path traversal protection on all run_id inputs (regex + resolved path check)
- 27 tests covering all PERS-01 and PERS-02 behaviors, 817 total tests passing

## Task Commits

1. **Task 1 RED: Failing tests** - `66ae7ac` (test)
2. **Task 1 GREEN: AutopilotRun implementation** - `bc2b2cc` (feat)
3. **Task 2: Update __init__.py re-exports** - `37ef922` (feat)

## Files Created/Modified

- `agentcouncil/autopilot/run.py` — AutopilotRunStatus, StageCheckpoint, AutopilotRun, persist, load_run, validate_transition, resume, _STAGE_ARTIFACT_CLASS
- `tests/test_autopilot_run.py` — 18 test functions (27 test cases) covering PERS-01 and PERS-02
- `agentcouncil/autopilot/__init__.py` — Added run.* wildcard export and _run_all in __all__

## Decisions Made

- `use_enum_values=True` means `run.status` is always a plain string — all comparisons in `resume()` and `validate_transition()` use string literals, not enum members
- `resume()` returns `(run, registry)` tuple without mutating the run — orchestrator decides whether to update status
- `_validate_run_id()` uses both regex and `(RUN_DIR / id).resolve().startswith(RUN_DIR.resolve())` for defense-in-depth
- `load_run()` does NOT call `_ensure_dir()` — `FileNotFoundError` is the correct signal when dir is missing

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Worktree was behind main by ~10 commits (phases 26-28). Resolved by merging main into the worktree branch before beginning execution.

## User Setup Required

None — no external service configuration required. Persistence directory (`~/.agentcouncil/autopilot/`) is created lazily on first `persist()` call.

## Next Phase Readiness

- Phase 30 orchestrator can now use `persist(run)` after every stage transition for durable state
- `resume(run_id)` provides clean restart from `paused_for_approval` and `paused_for_revision` states
- `validate_transition(current, next)` ready for orchestrator state change enforcement
- All exports accessible via `from agentcouncil.autopilot import AutopilotRun, persist, load_run, resume, validate_transition`

---
*Phase: 29-autopilot-run-state-+-persistence*
*Completed: 2026-04-15*
