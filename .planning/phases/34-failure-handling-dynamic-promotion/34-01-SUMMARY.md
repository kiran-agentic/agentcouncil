---
phase: 34-failure-handling-dynamic-promotion
plan: 01
subsystem: autopilot
tags: [orchestrator, retry-policy, tier-promotion, failure-handling, state-machine]

# Dependency graph
requires:
  - phase: 33-rule-based-router
    provides: detect_undeclared_sensitive_files, SENSITIVE_PATH_PATTERNS
  - phase: 29-autopilot-run-state-persistence
    provides: AutopilotRun, StageCheckpoint, persist, validate_transition, resume
  - phase: 30-linear-orchestrator
    provides: LinearOrchestrator, _run_gate, _run_stage_with_gate
provides:
  - _run_gate_with_retry: gate retry logic per manifest retry_policy (none/once/backend_fallback)
  - _apply_tier3_promotion: monotonic tier 3 promotion with persist, extracted from _maybe_promote_tier
  - _maybe_promote_from_gate: gate-outcome-driven tier promotion on challenge not_ready or review critical/high
  - Exhausted retry escalation to paused_for_approval with descriptive failure_reason
  - self._last_raw_artifact tracking in _run_gate for protocol artifact access
affects:
  - autopilot-workflows, server, any phase extending LinearOrchestrator behavior

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Gate retry: _run_gate_with_retry wraps _run_gate with policy-driven retry logic"
    - "Monotonic promotion: _apply_tier3_promotion is no-op if already tier 3, always persists"
    - "Raw artifact tracking: self._last_raw_artifact set by _run_gate, passed to _maybe_promote_from_gate"
    - "Exhaustion escalation: mirrors existing verify->build retry loop exhaustion pattern"

key-files:
  created: []
  modified:
    - agentcouncil/autopilot/orchestrator.py
    - tests/test_autopilot_orchestrator.py

key-decisions:
  - "[Phase 34]: _run_gate_with_retry uses local variables (not instance state) for retry tracking — no cross-call pollution"
  - "[Phase 34]: backend_fallback with no registered fallback runner falls through to retry primary once (same as 'once')"
  - "[Phase 34]: _last_raw_artifact set to None for injected gate_runners (return GateDecision directly, no raw artifact to inspect)"
  - "[Phase 34]: _apply_tier3_promotion extracted from _maybe_promote_tier — shared by both SAFE-04 (build files) and SAFE-05 (gate outcome) paths"
  - "[Phase 34]: Test for challenge not_ready uses _make_external_verify_registry so challenge gate fires for tier=2 (ORCH-05 condition)"

patterns-established:
  - "Raw artifact tracking: _run_gate sets self._last_raw_artifact before normalizing; injected gate_runners get None"
  - "Promotion helper: _apply_tier3_promotion is the single place that mutates tier, sets tier_promoted_at, and persists"
  - "Subclass test pattern: _InjectXxxOrchestrator overrides _run_gate to inject custom raw artifacts for promotion tests"

requirements-completed: [SAFE-05]

# Metrics
duration: 25min
completed: 2026-04-15
---

# Phase 34 Plan 01: Failure Handling + Dynamic Promotion Summary

**LinearOrchestrator extended with gate retry policy enforcement, exhaustion escalation to paused_for_approval, and gate-outcome-driven tier 3 promotion for challenge not_ready and review critical/high findings**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-15T10:08:33Z
- **Completed:** 2026-04-15T10:35:00Z
- **Tasks:** 2 (TDD: RED then GREEN)
- **Files modified:** 2

## Accomplishments

- Implemented `_run_gate_with_retry` enforcing `retry_policy` from `StageManifest` (none/once/backend_fallback) with fallback runner lookup
- Implemented `_apply_tier3_promotion` as shared monotonic helper extracted from `_maybe_promote_tier`, used by both SAFE-04 and SAFE-05 promotion paths
- Implemented `_maybe_promote_from_gate` inspecting raw protocol artifacts (ChallengeArtifact, ConvergenceResult, ReviewArtifact) for tier 3 triggers
- Wired retry + promotion into `_run_stage_with_gate`: gate exhaustion transitions to `paused_for_approval` with descriptive `failure_reason`
- Added 13 new tests (7 TestFailureHandling + 6 TestDynamicGatePromotion) covering all SAFE-05 success criteria
- Fixed pre-existing ChallengeArtifact stub bug (used old field names incompatible with current schema)
- Full test suite: 963 passed (was 950 before this phase)

## Task Commits

1. **Task 1: RED — Write failing tests for failure handling and gate-triggered promotion** - `92fc572` (test)
2. **Task 2: GREEN + REFACTOR — Implement failure handling and gate-triggered promotion** - `d0b1f6d` (feat)

## Files Created/Modified

- `agentcouncil/autopilot/orchestrator.py` — Added `_apply_tier3_promotion`, `_maybe_promote_from_gate`, `_run_gate_with_retry`; updated `_run_stage_with_gate` to use retry wrapper + promotion check; tracked `_last_raw_artifact` in `_run_gate`; fixed ChallengeArtifact stub fields
- `tests/test_autopilot_orchestrator.py` — Added `_ExceptionThenAdvanceGate`, `_AlwaysExceptionGate` helpers, `_make_registry_with_retry_policy`, `TestFailureHandling` (7 tests), `TestDynamicGatePromotion` (6 tests)

## Decisions Made

- `_run_gate_with_retry` returns a tuple `(GateDecision, raw_artifact)` rather than storing raw_artifact as a separate instance attribute, because `_run_gate` already sets `self._last_raw_artifact` and the tuple makes the data flow explicit at the call site in `_run_stage_with_gate`
- `backend_fallback` with no registered fallback runner silently retries primary gate once (same as `once`) — documented in docstring
- Test for `test_challenge_not_ready_promotes_to_tier3` uses `_make_external_verify_registry()` and pre-sets verify checkpoint to `blocked` to trigger the challenge gate for a tier=2 run without requiring tier=3 initial state

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ChallengeArtifact stub using old field names**
- **Found during:** Task 2 (GREEN — implement failure handling)
- **Issue:** `_run_gate` in orchestrator.py constructed `ChallengeArtifact` with `assumptions_tested`, `overall_confidence`, and `executive_summary` fields that no longer exist in the current schema; `summary` and `next_action` are required but were missing
- **Fix:** Updated stub to use correct fields: `summary="stub challenge gate"`, `failure_modes=[]`, `next_action="proceed"`
- **Files modified:** `agentcouncil/autopilot/orchestrator.py`
- **Verification:** `python3 -c "from agentcouncil.schemas import ChallengeArtifact; ..."` no longer raises ValidationError
- **Committed in:** d0b1f6d (Task 2 commit)

**2. [Rule 1 - Bug] Fixed test_gate_retry_backend_fallback_uses_fallback_runner to use exception-then-advance gate**
- **Found during:** Task 2 (GREEN — running tests after implementation)
- **Issue:** Test used `_AlwaysExceptionGate` for the global `review_loop` runner but only set `backend_fallback` on the `plan` stage. The build stage (also using `review_loop`) also got the always-failing gate with its default `once` retry_policy, exhausting retries and pausing the run before completion.
- **Fix:** Changed from `_AlwaysExceptionGate` to `_ExceptionThenAdvanceGate` (fails on call 1, advances on call 2+). The fallback gate handles plan's first failure, and build's gate call (call 2) succeeds.
- **Files modified:** `tests/test_autopilot_orchestrator.py`
- **Verification:** `python3 -m pytest tests/test_autopilot_orchestrator.py::TestFailureHandling::test_gate_retry_backend_fallback_uses_fallback_runner` passes
- **Committed in:** d0b1f6d (Task 2 commit)

**3. [Rule 1 - Bug] Fixed test_challenge_not_ready_promotes_to_tier3 challenge gate never firing**
- **Found during:** Task 2 (GREEN — running tests after implementation)
- **Issue:** Test started pipeline at verify stage with tier=2 and used default registry. `_should_run_challenge` returns False for tier=2 with local side effects, so the challenge gate was bypassed with `gate_type_override="none"`.
- **Fix:** Changed to use `_make_external_verify_registry()` (verify has `side_effect_level=external`) and pre-set verify checkpoint to `blocked` (simulating approval already granted) so the challenge gate fires.
- **Files modified:** `tests/test_autopilot_orchestrator.py`
- **Verification:** `python3 -m pytest tests/test_autopilot_orchestrator.py::TestDynamicGatePromotion::test_challenge_not_ready_promotes_to_tier3` passes
- **Committed in:** d0b1f6d (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 × Rule 1 - Bug)
**Impact on plan:** All auto-fixes required for correctness. ChallengeArtifact stub fix is a pre-existing bug not caught by prior tests. Test fixes align test setup with actual ORCH-05 semantics.

## Issues Encountered

None beyond the 3 bugs documented above.

## Known Stubs

None — all new methods have real implementations. No placeholder data flows to callers.

## Next Phase Readiness

- SAFE-05 is fully implemented and all 4 success criteria are covered by tests
- Phase 34 closes the final v2.0 requirement — all 28 v2.0 requirements are now implemented
- Full test suite is green at 963 tests
- No blockers

---
*Phase: 34-failure-handling-dynamic-promotion*
*Completed: 2026-04-15*
