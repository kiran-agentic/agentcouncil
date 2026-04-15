---
phase: 32-approval-boundary
plan: 01
subsystem: autopilot
tags: [orchestrator, safety, approval, autonomy-tiers, pydantic]

# Dependency graph
requires:
  - phase: 30-orchestrator
    provides: LinearOrchestrator with run_pipeline, _run_stage_with_gate, _find_stage_checkpoint
  - phase: 29-autopilot-run-state-persistence
    provides: AutopilotRun with tier field, StageCheckpoint with status field, persist/resume

provides:
  - "_classify_stage method on LinearOrchestrator — three-tier classification (executor/council/approval-gated)"
  - "_should_pause_for_approval method with already-blocked bypass for resume flow"
  - "Pre-execution approval guard in run_pipeline (SAFE-02) that fires before stage marking in_progress"
  - "TestApprovalBoundary test class with 9 tests covering SAFE-01 and SAFE-02"

affects: [33-router, 34-failure-handling, server.py autopilot tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_classify_stage feeds _should_pause_for_approval — classification is separated from decision"
    - "Already-blocked = already-approved pattern — checkpoint.status=blocked is the resume bypass signal"
    - "Pre-execution guard inserted before in_progress marking — prevents inconsistent intermediate state"

key-files:
  created: []
  modified:
    - agentcouncil/autopilot/orchestrator.py
    - tests/test_autopilot_orchestrator.py

key-decisions:
  - "[Phase 32]: _classify_stage gates on approval_required=True unconditionally and side_effect_level=external regardless of tier; tier=3 does NOT gate all stages — only external/approval_required stages are gated"
  - "[Phase 32]: Already-blocked checkpoint = already-approved (resume bypass) — calling autopilot_resume IS the approval; no new model fields needed"
  - "[Phase 32]: Pre-execution guard fires BEFORE marking in_progress to prevent inconsistent intermediate state"
  - "[Phase 32]: test_challenge_fires_for_external updated to use resume-after-approval pattern since external verify now triggers approval guard before challenge gate"

patterns-established:
  - "Pattern: classification feeds approval decision — _classify_stage returns tier label, _should_pause_for_approval uses it"
  - "Pattern: approval bypass via checkpoint status — blocked stage skips guard on resume"

requirements-completed: [SAFE-01, SAFE-02]

# Metrics
duration: 2min
completed: 2026-04-15
---

# Phase 32 Plan 01: Approval Boundary Summary

**Pre-execution approval guard on LinearOrchestrator using three-tier classification that blocks external/approval_required stages before any runner fires, with resume bypass via already-blocked checkpoint status**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-15T09:36:02Z
- **Completed:** 2026-04-15T09:38:45Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `_classify_stage(run, entry) -> str` returning executor/council/approval-gated per SAFE-01 classification rules
- Added `_should_pause_for_approval(run, entry) -> bool` with already-blocked bypass to prevent infinite re-blocking on resume
- Inserted SAFE-02 pre-execution guard in `run_pipeline` before any status mutation, transitions to `paused_for_approval` with blocked checkpoint
- Added TestApprovalBoundary (9 tests): 5 for _classify_stage unit cases, 4 for approval boundary integration including resume
- Full suite: 918 tests pass, 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — Write TestApprovalBoundary tests** - `c155d7a` (test)
2. **Task 2: GREEN — Implement _classify_stage, _should_pause_for_approval, and guard** - `9532e03` (feat)

_Note: TDD tasks — test commit first, then implementation commit_

## Files Created/Modified

- `agentcouncil/autopilot/orchestrator.py` — Added _classify_stage, _should_pause_for_approval methods and SAFE-02 pre-execution guard in run_pipeline; updated module docstring to include SAFE-01/SAFE-02
- `tests/test_autopilot_orchestrator.py` — Added TestApprovalBoundary class (9 tests), _make_external_stage_registry(), _make_approval_required_registry() helpers; updated test_challenge_fires_for_external to use resume-after-approval pattern

## Decisions Made

- tier=3 does NOT gate all stages — only external/approval_required stages are gated. The tier label (approval-gated) applies to those stages; pure local/none stages on tier=3 still go through council gate. This is the conservative, correct read of requirements.
- Already-blocked = already-approved: the act of calling autopilot_resume IS the approval. No new model fields (approval_granted: bool) needed — checkpoint.status != "blocked" is the guard bypass condition.
- Pre-execution guard placed before `checkpoint.status = "in_progress"` to prevent inconsistent intermediate state.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed regression in test_challenge_fires_for_external**
- **Found during:** Task 2 (GREEN implementation)
- **Issue:** The existing TestChallengeGate test `test_challenge_fires_for_external` used `_make_external_verify_registry()` (verify with external side effects, tier=2) and expected the challenge gate to fire after verify ran. With SAFE-02, the approval guard now fires before verify, so verify never ran and the challenge gate was never invoked. Test failed.
- **Fix:** Updated test to start from `verify` stage with verify checkpoint pre-set to `blocked` (approval already granted), simulating the resume-after-approval flow. Pre-populated artifact_registry with prior stage artifacts. This is architecturally correct: after approval is granted and resume called, verify's checkpoint is blocked, guard bypasses, runner fires, challenge gate evaluates.
- **Files modified:** tests/test_autopilot_orchestrator.py
- **Verification:** pytest tests/test_autopilot_orchestrator.py -x -q → 30 passed; full suite 918 passed
- **Committed in:** 9532e03 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix was necessary for no-regression success criterion. The test was not wrong in intent but needed updating to reflect the new approval-first architecture for external stages.

## Issues Encountered

None beyond the test_challenge_fires_for_external regression, which was auto-fixed inline.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SAFE-01 and SAFE-02 requirements complete; approval boundary is now the single enforced safety gate for external side effects
- Phase 33 (router) can now use _classify_stage as the classification authority for tier routing decisions
- Phase 34 (failure handling) inherits stable approval flow: paused_for_approval + blocked checkpoint is the canonical pause state
- server.py autopilot_resume_tool works as-is — it sets status=running which triggers the guard bypass via already-blocked checkpoint

---
*Phase: 32-approval-boundary*
*Completed: 2026-04-15*
