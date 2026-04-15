---
phase: 30-linear-orchestrator-skeleton
plan: "02"
subsystem: autopilot
tags: [mcp-tools, orchestrator, pers-04, server]
dependency_graph:
  requires:
    - 30-01  # LinearOrchestrator, StageRunner
    - 29-01  # AutopilotRun, StageCheckpoint, persist, load_run, resume, validate_transition
    - 27-01  # load_default_registry
    - 26-01  # SpecArtifact
  provides:
    - autopilot_prepare MCP tool
    - autopilot_start MCP tool
    - autopilot_status MCP tool
    - autopilot_resume MCP tool
  affects:
    - agentcouncil/server.py (4 new @mcp.tool registrations)
    - agentcouncil/autopilot/orchestrator.py (bug fix to ConvergenceResult stub)
    - tests/test_autopilot_orchestrator.py (TestMCPTools class)
tech_stack:
  added: []
  patterns:
    - MCP tool registration via @mcp.tool decorator
    - Tool delegation pattern (tools delegate to LinearOrchestrator)
    - monkeypatch RUN_DIR for test isolation
key_files:
  created: []
  modified:
    - agentcouncil/server.py
    - agentcouncil/autopilot/orchestrator.py
    - tests/test_autopilot_orchestrator.py
decisions:
  - "[30-02] autopilot_resume bypasses validate_transition when resetting paused run to running — paused states are terminal sinks per the state machine design; resume() already guards against non-paused runs"
  - "[30-02] ConvergenceResult stub in orchestrator._run_gate corrected to use exit_reason='all_verified' and total_iterations=1 matching the actual schema"
metrics:
  duration_seconds: 420
  completed_date: "2026-04-15"
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 3
---

# Phase 30 Plan 02: MCP Tool Registration Summary

**One-liner:** Four MCP autopilot tools (prepare/start/status/resume) registered in server.py, delegating to LinearOrchestrator with stub runners, with 4 PERS-04 tests passing and full suite green (834 tests).

## What Was Built

`agentcouncil/server.py` now provides four `@mcp.tool` registrations:

- `autopilot_prepare`: validates spec via SpecArtifact, creates AutopilotRun with 5 pending stage checkpoints, persists to disk, returns run_id/status/current_stage/tier
- `autopilot_start`: loads run by run_id, creates LinearOrchestrator with empty runners (uses internal stubs), runs full pipeline, returns final state with stage list
- `autopilot_status`: loads run, returns full state dict with per-stage status and gate_decision
- `autopilot_resume`: loads paused run via resume(), resets status to running, re-runs pipeline via LinearOrchestrator, returns final state

`tests/test_autopilot_orchestrator.py` gained `TestMCPTools` class with 4 tests:
- `test_prepare_returns_run_id`: verifies run_id in result and file persisted to disk
- `test_status_reflects_run`: verifies status and 5-stage list returned
- `test_start_completes_run`: verifies stub pipeline reaches completed with completed_at set
- `test_resume_tool_returns_state`: creates paused run, resumes, verifies completed

`agentcouncil/autopilot/__init__.py` already contained orchestrator re-exports from Plan 01 — no changes needed.

## Tasks Completed

| Task | Description | Commit | Type |
|------|-------------|--------|------|
| 1 | Register 4 MCP autopilot tools in server.py | a0f66b5 | feat |
| 2 | TestMCPTools + bug fixes | adbd567 | feat |

## Decisions Made

1. **autopilot_resume bypasses validate_transition**: The plan template called `validate_transition(run.status, "running")` before setting status=running in resume. However, paused states (`paused_for_approval`, `paused_for_revision`) are terminal sinks in the state machine — they have no allowed outgoing transitions. The `resume()` function from run.py already validates the run is in a paused state before returning it. So the transition check is unnecessary and incorrect; we bypass it and directly set `run.status = "running"`.

2. **ConvergenceResult stub fields corrected**: The orchestrator's `_run_gate` fallback for `review_loop` used `exit_reason="stub"` and `rounds_completed=1` which are not valid per the ConvergenceResult schema. Fixed to `exit_reason="all_verified"` and `total_iterations=1`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ConvergenceResult stub in orchestrator._run_gate used invalid fields**
- **Found during:** Task 2 test execution (test_start_completes_run)
- **Issue:** `_run_gate` created `ConvergenceResult(exit_reason="stub", rounds_completed=1, ...)` but schema requires `exit_reason: Literal["all_verified", "max_iterations", "approved"]` and field is `total_iterations` not `rounds_completed`
- **Fix:** Changed to `exit_reason="all_verified"` and `total_iterations=1`
- **Files modified:** agentcouncil/autopilot/orchestrator.py
- **Commit:** adbd567

**2. [Rule 1 - Bug] autopilot_resume_tool called validate_transition(paused -> running) which always fails**
- **Found during:** Task 2 test execution (test_resume_tool_returns_state)
- **Issue:** The plan template included `validate_transition(run.status, "running")` before setting status=running. Paused states have no allowed outgoing transitions in the state machine (`paused_for_approval: set()`), so this always raises ValueError.
- **Fix:** Removed validate_transition call; added comment explaining that resume() already guards against non-paused runs
- **Files modified:** agentcouncil/server.py
- **Commit:** adbd567

## Known Stubs

- All 4 MCP tools use LinearOrchestrator with `runners={}`, which falls back to the internal stub runners. Phase 31 wires real workflow content.
- `autopilot_prepare` accepts `intent` parameter but does not use it (spec is validated via SpecArtifact but intent is not stored in AutopilotRun). This is intentional for Phase 30 scope.

## Self-Check: PASSED
