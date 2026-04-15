---
phase: 30-linear-orchestrator-skeleton
plan: "01"
subsystem: autopilot
tags: [orchestrator, state-machine, gate-loop, orch-03, orch-05, tdd]
dependency_graph:
  requires:
    - 26-01  # SpecArtifact, PlanArtifact, BuildArtifact, VerifyArtifact, ShipArtifact, GateDecision
    - 26-02  # BuildArtifact, VerifyArtifact, ShipArtifact output-side models
    - 27-01  # StageRegistryEntry, StageManifest, load_default_registry
    - 28-01  # GateNormalizer
    - 29-01  # AutopilotRun, StageCheckpoint, persist, validate_transition, resume
  provides:
    - LinearOrchestrator (run_pipeline, gate loop, conditional challenge)
    - StageRunner type alias
  affects:
    - agentcouncil/autopilot/__init__.py (re-export)
tech_stack:
  added: []
  patterns:
    - TDD (RED → GREEN → REFACTOR)
    - Gate-type override pattern for conditional ORCH-05 challenge
    - Injectable gate_runners for test isolation
    - Stub artifact factories for default runners
key_files:
  created:
    - agentcouncil/autopilot/orchestrator.py
    - tests/test_autopilot_orchestrator.py
  modified:
    - agentcouncil/autopilot/__init__.py
decisions:
  - "[30-01] Challenge gate is conditional via gate_type_override: verify's default_gate=challenge is overridden to none for tier=2 non-external runs — no separate post-verify gate step"
  - "[30-01] _run_challenge_gate removed — challenge gating is unified in _run_stage_with_gate with gate_type_override parameter"
  - "[30-01] Injectable gate_runners dict (keyed by gate_type string) used for all test isolation — avoids mocking internal methods"
metrics:
  duration_seconds: 289
  completed_date: "2026-04-15"
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 1
---

# Phase 30 Plan 01: LinearOrchestrator Skeleton Summary

**One-liner:** LinearOrchestrator sequences stub stages through spec_prep -> plan -> build -> verify -> ship with gate loop (advance/revise/block), persist at every checkpoint, and conditional challenge gate via ORCH-05 (tier=3 or side_effect_level=external).

## What Was Built

`agentcouncil/autopilot/orchestrator.py` provides:

- `LinearOrchestrator` class wiring all Phase 26-29 modules together
- `run_pipeline(run, artifact_registry)` — iterates stages via `allowed_next`, runs gate loop per stage, persists after every state change
- `_run_stage_with_gate` — executes work stage in revise loop; handles advance/revise/block decisions
- `_should_run_challenge` — ORCH-05: returns True for tier=3 or side_effect_level=external
- `_find_stage_checkpoint` — finds or creates StageCheckpoint in run.stages
- `_run_gate` — dispatches to injectable gate_runners or stub normalizer
- Default stub runners (`_default_stub_runner`) for all 5 pipeline stages
- `StageRunner` type alias: `Callable[[AutopilotRun, dict, Optional[str]], Any]`

`tests/test_autopilot_orchestrator.py` provides 13 tests across 5 classes:

- `TestEndToEnd` (2): happy path reaches completed, run persisted to disk
- `TestReviseLoop` (2): plan runner called twice with revision_guidance, gate call count tracked
- `TestBlockHalt` (3): block sets paused_for_approval, run persisted, stage checkpoint blocked
- `TestResume` (2): resume continues from blocked to completed, persisted with completed status
- `TestChallengeGate` (4): fires for external, fires for tier=3, skipped for tier=2/local, default_gate=none stages unaffected

## Tasks Completed

| Task | Description | Commit | Type |
|------|-------------|--------|------|
| RED | Failing tests for LinearOrchestrator | f8eca7d | test |
| GREEN+REFACTOR | LinearOrchestrator implementation | f6ab394 | feat |

## Decisions Made

1. **Challenge gate via gate_type_override**: The verify manifest has `default_gate: challenge`. ORCH-05 controls whether this gate runs by overriding gate_type to "none" for non-qualifying runs (tier=2 + non-external). This avoids a separate post-verify challenge step and keeps the gate loop unified.

2. **_run_challenge_gate removed during refactor**: An initially drafted `_run_challenge_gate` method was removed once the gate_type_override approach proved cleaner — one method `_run_stage_with_gate` handles all gate logic.

3. **Injectable gate_runners dict**: Tests inject gate behavior via `gate_runners: dict[str, Callable[[], GateDecision]]`. This avoids patching internal methods and makes test intent explicit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stub artifact field names corrected**
- **Found during:** GREEN phase
- **Issue:** Plan's stub factories used outdated field names (`files_modified`, `environment`, `criteria`, `commit_sha`, `verification_status`) that no longer match artifacts.py v26-02 schema
- **Fix:** Updated all stub factories to use actual field names: `files_changed`, `verification_notes`, `test_environment`, `criteria_verdicts`, `evidence_summary`, `mock_policy`, `overall_status`, `head_sha`, `worktree_clean`, etc.
- **Files modified:** tests/test_autopilot_orchestrator.py, agentcouncil/autopilot/orchestrator.py

**2. [Rule 1 - Bug] Separate post-verify challenge gate removed**
- **Found during:** RED → GREEN phase
- **Issue:** Test `test_challenge_skipped_for_tier2` failed because verify's `default_gate: challenge` was firing unconditionally in `_run_stage_with_gate` BEFORE the post-verify conditional check in `run_pipeline`. The challenge gate was called twice for tier=3/external and once spuriously for tier=2.
- **Fix:** Removed separate `_run_challenge_gate` method. Added `gate_type_override` parameter to `_run_stage_with_gate`. `run_pipeline` sets override to "none" when `_should_run_challenge` returns False, allowing verify to advance without challenge gate.
- **Files modified:** agentcouncil/autopilot/orchestrator.py

## Known Stubs

None — the plan goal is the orchestrator skeleton itself. All stage runners are intentionally stub (minimal valid artifacts). Phase 31 wires real workflow content into these runners.

## Self-Check: PASSED
