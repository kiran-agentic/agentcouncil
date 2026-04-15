---
phase: 31-workflows-spec-prep-verify
plan: "04"
subsystem: autopilot
tags: [orchestrator, retry-loop, verify, build, server, runners, stage-runner, VER-04]
dependency_graph:
  requires:
    - agentcouncil/autopilot/orchestrator.py (LinearOrchestrator run_pipeline)
    - agentcouncil/autopilot/artifacts.py (VerifyArtifact.retry_recommendation field)
    - agentcouncil/autopilot/prep.py (run_spec_prep — Plan 02)
    - agentcouncil/autopilot/verify.py (run_verify — Plan 03)
    - agentcouncil/autopilot/ship.py (run_ship — Plan 03)
  provides:
    - verify->build retry loop in LinearOrchestrator.run_pipeline (max 2 retries, escalates to paused_for_approval)
    - server.py autopilot_start_tool and autopilot_resume_tool with real runners
    - __init__.py re-exports for prep, verify, ship modules
    - workflow content validation tests (attribution + content length)
  affects:
    - agentcouncil/server.py (uses real runners now)
    - agentcouncil/autopilot/__init__.py (public API surface expanded)
    - tests/test_autopilot_orchestrator.py (TestVerifyRetryLoop class)
    - tests/test_autopilot_loader.py (workflow content tests)
tech-stack:
  added: []
  patterns:
    - Verify->build retry loop with runner wrapper to inject revision_guidance on first call
    - _build_retry_count instance attribute reset at orchestrator construction, not per-pipeline
    - Closure-based guidance injection via _wrapped_first_call sentinel list

key-files:
  created: []
  modified:
    - agentcouncil/autopilot/orchestrator.py
    - agentcouncil/server.py
    - agentcouncil/autopilot/__init__.py
    - tests/test_autopilot_orchestrator.py
    - tests/test_autopilot_loader.py

key-decisions:
  - "Verify->build retry loop uses a closure wrapper around build runner to inject rev_guidance on first call without changing _run_stage_with_gate signature"
  - "server.py registers real runners for spec_prep, verify, ship; plan and build remain stubs until Phase 32"
  - "_build_retry_count initialized in __init__ (not reset per pipeline call) — sufficient for single-use orchestrator per MCP tool invocation"

requirements-completed: [VER-04]

duration: 4min
completed: "2026-04-15"
---

# Phase 31 Plan 04: Wire Retry Loop + Register Real Runners Summary

**Verify->build retry loop in LinearOrchestrator (max 2 retries, paused_for_approval escalation) with real stage runners registered in server.py for spec_prep, verify, and ship stages**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-15T09:20:00Z
- **Completed:** 2026-04-15T09:24:28Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Orchestrator detects `retry_recommendation="retry_build"` in VerifyArtifact and re-runs build with `revision_guidance`, then re-runs verify — capped at 2 retries
- After exhausting retries, orchestrator escalates to `status=paused_for_approval` with `failure_reason` containing "retry loop exhausted"
- `server.py` now imports and registers `run_spec_prep`, `run_verify`, `run_ship` as real runners in both `autopilot_start_tool` and `autopilot_resume_tool`
- `agentcouncil/autopilot/__init__.py` re-exports all three new modules (prep, verify, ship) with merged `__all__`
- Two new loader tests validate: vendored workflow attribution headers present (plan/build/ship) and all workflow.md files have >500 chars of real content

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Add failing TestVerifyRetryLoop tests** - `acafa44` (test)
2. **Task 1 GREEN: Implement verify->build retry loop in orchestrator** - `1eb54f1` (feat)
3. **Task 2: Register real runners + __init__.py + workflow content tests** - `fa39d78` (feat)

## Files Created/Modified

- `agentcouncil/autopilot/orchestrator.py` — Added `_build_retry_count` attribute and VER-04 verify->build retry loop in `run_pipeline`
- `agentcouncil/server.py` — Import real runners; register in `autopilot_start_tool` and `autopilot_resume_tool`; updated docstring removing Phase 30 stub notes
- `agentcouncil/autopilot/__init__.py` — Added prep/ship/verify re-exports and merged `__all__`
- `tests/test_autopilot_orchestrator.py` — Added `TestVerifyRetryLoop` class with 4 tests
- `tests/test_autopilot_loader.py` — Added `test_vendored_workflow_attribution` and `test_default_registry_workflow_content_is_real`

## Decisions Made

- Guidance injection into re-run build uses a closure wrapper (`_build_with_guidance`) with a `_wrapped_first_call` sentinel, so the first call receives `rev_guidance` from the failed VerifyArtifact. This avoids changing `_run_stage_with_gate`'s signature.
- `server.py` registers real runners only for `spec_prep`, `verify`, `ship`. `plan` and `build` remain stubs since their real workflow execution (Claude Code invocation) is Phase 32 scope.
- `_build_retry_count` is instance-level (not reset per `run_pipeline` call). Since each MCP tool invocation creates a fresh `LinearOrchestrator`, this is equivalent to per-pipeline tracking.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all acceptance criteria passed on first implementation attempt.

## Known Stubs

None — all implementations are functional. Plan and build stage runners remain as stubs intentionally; their real workflow execution is Phase 32 scope (not a stub introduced by this plan).

## Next Phase Readiness

- Phase 31 is complete: all 17 requirements addressed across Plans 01-04
- Full autopilot pipeline is wired: spec_prep, verify, ship use real runners; plan/build use stubs
- Verify->build retry loop functional and tested
- Phase 32 (approval gates / human-in-the-loop) can proceed

## Self-Check: PASSED
