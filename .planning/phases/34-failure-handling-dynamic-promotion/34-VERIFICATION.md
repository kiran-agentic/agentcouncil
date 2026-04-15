---
phase: 34-failure-handling-dynamic-promotion
verified: 2026-04-15T11:00:00Z
status: passed
score: 4/4 must-haves verified
gaps: []
human_verification: []
---

# Phase 34: Failure Handling + Dynamic Promotion Verification Report

**Phase Goal:** The system recovers gracefully from protocol timeouts, exhausted retries, and mid-execution surprises while maintaining a complete checkpoint for every partial completion
**Verified:** 2026-04-15T11:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                                                                              | Status     | Evidence                                                                                                    |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------- |
| 1   | When a gate raises an exception, the orchestrator retries per the stage manifest retry_policy before escalating                                    | VERIFIED   | `_run_gate_with_retry` at line 707 implements none/once/backend_fallback logic; wired at line 520           |
| 2   | After retries are exhausted, the run transitions to paused_for_approval with a descriptive failure_reason                                          | VERIFIED   | Lines 524–535: exception catch sets `checkpoint.status="blocked"`, `failure_reason`, `status="paused_for_approval"`, persists |
| 3   | A run that fails mid-pipeline has StageCheckpoints with artifact_snapshot for each completed stage, and resume continues from the last checkpoint  | VERIFIED   | `test_mid_pipeline_failure_has_checkpoints` and `test_resume_after_gate_failure_continues_from_checkpoint` both PASS |
| 4   | When a challenge gate returns not_ready or a review gate finds critical/high severity findings, the run tier is promoted to 3 and persisted before the next stage executes | VERIFIED   | `_maybe_promote_from_gate` (line 660) + `_apply_tier3_promotion` (line 646) confirmed; `test_promotion_persisted_before_next_stage` PASSES |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact                                         | Expected                                                                | Status     | Details                                                                                   |
| ------------------------------------------------ | ----------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------- |
| `agentcouncil/autopilot/orchestrator.py`         | `_run_gate_with_retry`, `_apply_tier3_promotion`, `_maybe_promote_from_gate` | VERIFIED   | All 3 methods present; grep count = 8 occurrences across definitions + call sites        |
| `tests/test_autopilot_orchestrator.py`           | `TestFailureHandling` and `TestDynamicGatePromotion` test classes       | VERIFIED   | Both classes present with 7 + 6 tests respectively; all 13 PASS                          |

### Key Link Verification

| From                                     | To                                       | Via                                                           | Status  | Details                                                              |
| ---------------------------------------- | ---------------------------------------- | ------------------------------------------------------------- | ------- | -------------------------------------------------------------------- |
| `agentcouncil/autopilot/orchestrator.py` | `agentcouncil/autopilot/loader.py`       | `entry.manifest.retry_policy` in `_run_stage_with_gate`       | WIRED   | Lines 521, 528 both read `entry.manifest.retry_policy`              |
| `agentcouncil/autopilot/orchestrator.py` | `agentcouncil/schemas.py`                | `ChallengeArtifact.readiness` and `Finding.severity` checks   | WIRED   | `_maybe_promote_from_gate` lines 683–705 inspect both artifact types |
| `agentcouncil/autopilot/orchestrator.py` | `agentcouncil/autopilot/run.py`          | `persist(run)` called inside `_apply_tier3_promotion`         | WIRED   | Line 658 calls `persist(run)` unconditionally on promotion           |

### Data-Flow Trace (Level 4)

| Artifact                                 | Data Variable    | Source                                     | Produces Real Data | Status    |
| ---------------------------------------- | ---------------- | ------------------------------------------ | ------------------ | --------- |
| `agentcouncil/autopilot/orchestrator.py` | `raw_artifact`   | `self._last_raw_artifact` set in `_run_gate` | Yes — set from protocol stub before normalization | FLOWING |
| `agentcouncil/autopilot/orchestrator.py` | `gate_decision, raw_artifact` | `_run_gate_with_retry` tuple return | Yes — real GateDecision + raw artifact from gate | FLOWING |

### Behavioral Spot-Checks

| Behavior                                                          | Command                                                                                                    | Result          | Status  |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------- | ------- |
| All 13 new tests pass (TestFailureHandling + TestDynamicGatePromotion) | `python3 -m pytest tests/test_autopilot_orchestrator.py::TestFailureHandling tests/test_autopilot_orchestrator.py::TestDynamicGatePromotion -q` | 13 passed       | PASS    |
| Full test suite passes without regression                         | `python3 -m pytest tests/ -q --tb=no`                                                                      | 963 passed (was 950 pre-phase) | PASS    |
| retry_policy wired in `_run_stage_with_gate`                      | `grep "entry.manifest.retry_policy" agentcouncil/autopilot/orchestrator.py`                               | 2 matches       | PASS    |
| All 3 new methods present in orchestrator                         | `grep -c "_run_gate_with_retry\|_apply_tier3_promotion\|_maybe_promote_from_gate" orchestrator.py`        | 8 occurrences   | PASS    |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                   | Status    | Evidence                                                                                   |
| ----------- | ----------- | ----------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------ |
| SAFE-05     | 34-01-PLAN  | Failure handling with retry policy, escalation, and partial completion checkpoints | SATISFIED | All 4 success criteria covered: SC1 retry tests, SC2 exhaustion escalation, SC3 checkpoint resume, SC4 dynamic promotion |

### Anti-Patterns Found

None found. Scanned both `agentcouncil/autopilot/orchestrator.py` and `tests/test_autopilot_orchestrator.py` for TODO/FIXME/HACK/PLACEHOLDER markers, empty returns, and hardcoded stub data. No issues detected.

### Human Verification Required

None. All behaviors verified programmatically via test execution.

### Gaps Summary

No gaps. All must-have truths are verified, artifacts are substantive and wired, key links are confirmed, SAFE-05 is fully satisfied, and the full test suite is green at 963 tests.

---

_Verified: 2026-04-15T11:00:00Z_
_Verifier: Claude (gsd-verifier)_
