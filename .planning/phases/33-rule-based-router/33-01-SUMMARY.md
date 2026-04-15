---
phase: 33-rule-based-router
plan: "01"
subsystem: autopilot
tags: [safety, tier-routing, classification, promotion, tdd]
dependency_graph:
  requires: [29-01, 30-01, 31-01, 32-01]
  provides: [SAFE-03, SAFE-04]
  affects: [agentcouncil/autopilot/router.py, agentcouncil/autopilot/orchestrator.py, agentcouncil/server.py]
tech_stack:
  added: []
  patterns: [rule-based-routing, monotonic-tier-promotion, audit-field-on-model]
key_files:
  created:
    - agentcouncil/autopilot/router.py
    - tests/test_autopilot_router.py
  modified:
    - agentcouncil/autopilot/run.py
    - agentcouncil/autopilot/prep.py
    - agentcouncil/autopilot/orchestrator.py
    - agentcouncil/autopilot/__init__.py
    - agentcouncil/server.py
    - tests/test_autopilot_orchestrator.py
decisions:
  - "SENSITIVE_PATH_PATTERNS defined in router.py and imported by prep.py — single canonical source; prep.py extends with .env for codebase scan"
  - "classify_run called in autopilot_prepare_tool — fires exactly once before execution, never on resume"
  - "spec_target_files added to AutopilotRun to provide declared paths to orchestrator without reaching into artifact_registry"
  - "_maybe_promote_tier fires after any stage that produces files_changed attribute — not build-only, covers any future stage returning BuildArtifact-like artifacts"
metrics:
  duration_seconds: 243
  completed_date: "2026-04-15"
  tasks_completed: 2
  files_changed: 8
---

# Phase 33 Plan 01: Rule-Based Tier Router Summary

**One-liner:** Rule-based tier router classifying runs from SpecArtifact.target_files (SAFE-03) with sticky mid-run promotion on undeclared sensitive files via BuildArtifact.files_changed (SAFE-04).

## What Was Built

### Task 1: router.py module + AutopilotRun field + prep.py refactor (commit b33ca45)

- **`agentcouncil/autopilot/router.py`** — new module with:
  - `SENSITIVE_PATH_PATTERNS: list[str]` = ["auth", "migrations", "infra", "deploy", "permissions"] (canonical; `.env` excluded by design — belongs to prep.py's codebase scan)
  - `classify_run(spec, requested_tier=2) -> tuple[int, str]` — case-insensitive path matching; only promotes, never demotes
  - `detect_undeclared_sensitive_files(declared, actual) -> list[str]` — pattern-coverage semantics (declaring `src/auth/login.py` covers ALL auth paths)
- **`agentcouncil/autopilot/run.py`** — added `tier_classification_reason: Optional[str] = None` and `spec_target_files: list[str] = []` to `AutopilotRun`
- **`agentcouncil/autopilot/prep.py`** — replaced hardcoded `_SENSITIVE_PATTERNS` with import from `router.py` + append `.env`
- **`tests/test_autopilot_router.py`** — 27 unit tests: `TestClassifyRun` (12), `TestDetectUndeclaredSensitiveFiles` (10), `TestTierClassificationReason` (5)

### Task 2: Wire into server.py and orchestrator.py + integration tests (commit 7d09904)

- **`agentcouncil/server.py`** — `autopilot_prepare_tool`:
  - New `target_files: list[str] = []` parameter
  - Calls `classify_run(spec, requested_tier=tier)` immediately after SpecArtifact construction
  - Passes `computed_tier`, `tier_classification_reason`, and `spec_target_files` to `AutopilotRun`
  - Returns `tier_classification_reason` in response dict
- **`agentcouncil/autopilot/orchestrator.py`**:
  - Added `detect_undeclared_sensitive_files` import and `datetime`/`timezone` imports
  - New `_maybe_promote_tier(run, declared_paths, actual_paths)` method — monotonic promotion with ISO timestamp and persist
  - Wired into `run_pipeline` after each `_run_stage_with_gate` call — checks `files_changed` on any stage artifact
- **`agentcouncil/autopilot/__init__.py`** — added router re-export
- **`tests/test_autopilot_orchestrator.py`** — added `TestRuleBasedRouter` (5 integration tests): tier3 for sensitive target_files, promotion on undeclared build paths, no promotion when declared, sticky tier across stages, no demotion on resume

## Test Results

- `pytest tests/test_autopilot_router.py -x -q` — **27 passed**
- `pytest tests/test_autopilot_orchestrator.py -x -q` — **35 passed** (30 existing + 5 new)
- `pytest tests/ -x -q` — **950 passed, 0 failures** (12 deselected = integration tests needing live backends)

## Deviations from Plan

None — plan executed exactly as written.

The plan's action step referenced adding `spec_target_files` to `AutopilotRun` (step 2 of Task 2 action), which was also a natural follow-on from adding `tier_classification_reason`. Both fields were added as specified.

## Known Stubs

None. The router, classify_run, detect_undeclared_sensitive_files, and _maybe_promote_tier are all fully wired. The tier classification is exercised end-to-end in integration tests.

## Self-Check: PASSED

Files created/verified:
- `/Users/kirankrishna/Documents/agentcouncil/agentcouncil/autopilot/router.py` — exists
- `/Users/kirankrishna/Documents/agentcouncil/tests/test_autopilot_router.py` — exists
- `/Users/kirankrishna/Documents/agentcouncil/.planning/phases/33-rule-based-router/33-01-SUMMARY.md` — this file

Commits verified:
- b33ca45 — feat(33-01): implement rule-based tier router with SAFE-03 classification
- 7d09904 — feat(33-01): wire classify_run into server.py and _maybe_promote_tier into orchestrator
