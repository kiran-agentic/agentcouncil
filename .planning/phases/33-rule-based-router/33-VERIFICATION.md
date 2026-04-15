---
phase: 33-rule-based-router
verified: 2026-04-15T10:30:00Z
status: passed
score: 6/6 must-haves verified
---

# Phase 33: Rule-Based Router Verification Report

**Phase Goal:** Every stage receives an autonomy tier assignment based on declared intent before execution begins, and tier promotions are sticky for the remainder of the run
**Verified:** 2026-04-15
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                     | Status     | Evidence                                                                                                                    |
|----|-------------------------------------------------------------------------------------------|------------|-----------------------------------------------------------------------------------------------------------------------------|
| 1  | A spec with target_files containing auth/ or migrations/ etc gets tier=3 before execution | ✓ VERIFIED | `classify_run` checks path.lower() against SENSITIVE_PATH_PATTERNS; server.py calls it immediately after SpecArtifact construction before AutopilotRun is created |
| 2  | A spec with no sensitive target_files keeps the requested tier (default 2)                | ✓ VERIFIED | `classify_run` returns `(requested_tier, "no sensitive paths...")` when no match found; test_non_sensitive_path_preserves_requested_tier passes |
| 3  | classify_run never demotes — if requested_tier=3 and no sensitive paths, result is still 3 | ✓ VERIFIED | Return path is `return requested_tier, ...` — if caller passes 3 it stays 3; test_no_demotion_when_requested_tier_already_3 passes |
| 4  | When a build stage touches an undeclared sensitive file, tier promotes to 3 for the rest of the run | ✓ VERIFIED | `_maybe_promote_tier` in orchestrator.py fires after each `_run_stage_with_gate`; test_tier_promotion_on_undeclared_sensitive_build passes |
| 5  | Promoted tier is sticky — no demotion on subsequent stages or resume                      | ✓ VERIFIED | Promotion uses `run.tier = 3` (monotonic assignment); persisted to disk via `persist(run)`; test_promotion_sticky_across_stages and test_no_demotion_on_resume both pass |
| 6  | Tier classification reason is logged in AutopilotRun state for auditability               | ✓ VERIFIED | `tier_classification_reason: Optional[str] = None` added to AutopilotRun at line 100 of run.py; set in server.py autopilot_prepare_tool and returned in response dict |

**Score:** 6/6 truths verified

---

### Required Artifacts

| Artifact                                   | Expected                                                    | Status     | Details                                                                                 |
|--------------------------------------------|-------------------------------------------------------------|------------|-----------------------------------------------------------------------------------------|
| `agentcouncil/autopilot/router.py`         | classify_run and detect_undeclared_sensitive_files functions | ✓ VERIFIED | 114 lines; exports classify_run, detect_undeclared_sensitive_files, SENSITIVE_PATH_PATTERNS in `__all__` |
| `tests/test_autopilot_router.py`           | Unit tests for router module containing TestClassifyRun      | ✓ VERIFIED | 274 lines; 3 test classes: TestClassifyRun (12), TestDetectUndeclaredSensitiveFiles (10), TestTierClassificationReason (5) — 27 tests, all pass |

---

### Key Link Verification

| From                                      | To                                         | Via                                              | Status     | Details                                                                                         |
|-------------------------------------------|--------------------------------------------|--------------------------------------------------|------------|-------------------------------------------------------------------------------------------------|
| `agentcouncil/server.py`                  | `agentcouncil/autopilot/router.py`         | classify_run called in autopilot_prepare_tool    | ✓ WIRED    | Line 45: `from agentcouncil.autopilot.router import classify_run`; line 1183: `computed_tier, tier_reason = classify_run(spec, requested_tier=tier)` |
| `agentcouncil/autopilot/orchestrator.py`  | `agentcouncil/autopilot/router.py`         | _maybe_promote_tier calls detect_undeclared_sensitive_files | ✓ WIRED | Line 37: `from agentcouncil.autopilot.router import detect_undeclared_sensitive_files`; line 637: `undeclared = detect_undeclared_sensitive_files(declared_paths, actual_paths)` |
| `agentcouncil/autopilot/run.py`           | tier_classification_reason field           | AutopilotRun model field                         | ✓ WIRED    | Line 100: `tier_classification_reason: Optional[str] = None`; field persists through JSON round-trip per TestTierClassificationReason tests |

---

### Data-Flow Trace (Level 4)

| Artifact                             | Data Variable         | Source                            | Produces Real Data | Status      |
|--------------------------------------|-----------------------|-----------------------------------|--------------------|-------------|
| `agentcouncil/server.py` (prepare)   | computed_tier, tier_reason | classify_run(spec, requested_tier=tier) | Yes — derives from SpecArtifact.target_files loop | ✓ FLOWING |
| `agentcouncil/autopilot/orchestrator.py` (_maybe_promote_tier) | undeclared | detect_undeclared_sensitive_files(run.spec_target_files, actual_files) | Yes — derives from artifact files_changed vs declared spec paths | ✓ FLOWING |
| `agentcouncil/autopilot/run.py`      | tier_classification_reason, spec_target_files | set in autopilot_prepare_tool, persisted to disk | Yes — real values from classification | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior                                  | Command                                                                                   | Result         | Status  |
|-------------------------------------------|-------------------------------------------------------------------------------------------|----------------|---------|
| 27 router unit tests pass                 | `pytest tests/test_autopilot_router.py -x -q`                                            | 27 passed      | ✓ PASS  |
| 5 TestRuleBasedRouter integration tests pass | `pytest tests/test_autopilot_orchestrator.py::TestRuleBasedRouter -x -q`              | 5 passed       | ✓ PASS  |
| Full orchestrator suite (35 tests) pass   | `pytest tests/test_autopilot_orchestrator.py -q`                                         | 35 passed      | ✓ PASS  |
| Full test suite passes with no regressions | `pytest tests/ -x -q` (12 deselected = integration tests requiring live backends)       | 950 passed, 0 failures | ✓ PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description                                                                   | Status      | Evidence                                                                                               |
|-------------|-------------|-------------------------------------------------------------------------------|-------------|--------------------------------------------------------------------------------------------------------|
| SAFE-03     | 33-01-PLAN  | Rule-based router classifies stages by declared intent (target_files, side_effect_level) | ✓ SATISFIED | classify_run in router.py; wired into autopilot_prepare_tool; target_files param added to tool; REQUIREMENTS.md line 47 marked [x] |
| SAFE-04     | 33-01-PLAN  | Dynamic tier promotion when sensitive files detected mid-execution (sticky for remainder of run) | ✓ SATISFIED | _maybe_promote_tier in orchestrator.py; detect_undeclared_sensitive_files; spec_target_files on AutopilotRun; REQUIREMENTS.md line 48 marked [x] |

No orphaned requirements. Both IDs declared in PLAN frontmatter appear in REQUIREMENTS.md and are implemented.

---

### Anti-Patterns Found

No blockers or warnings found.

- `router.py`: No TODO/FIXME, no return null, no placeholder implementations. All functions are substantive.
- `orchestrator.py` (_maybe_promote_tier): Monotonic promotion with persist call and ISO timestamp — no empty handler.
- `server.py` (autopilot_prepare_tool): target_files passed through to SpecArtifact and classify_run — no hardcoded empty data at the call site.
- `run.py`: Both new fields (tier_classification_reason, spec_target_files) have proper defaults and are used.
- `prep.py`: _SENSITIVE_PATTERNS correctly imports from router.py and extends with ".env" — single canonical source achieved.

---

### Human Verification Required

None. All behaviors are programmatically verifiable and tests pass.

---

### Gaps Summary

No gaps. All 6 must-have truths are verified. Both required artifacts exist, are substantive, are wired, and have real data flowing through them. Both requirement IDs (SAFE-03, SAFE-04) are satisfied. The full test suite (950 tests) passes with zero failures.

Commits b33ca45 and 7d09904 exist in the repository and match the SUMMARY descriptions exactly.

---

_Verified: 2026-04-15_
_Verifier: Claude (gsd-verifier)_
