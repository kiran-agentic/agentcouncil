---
phase: 31-workflows-spec-prep-verify
plan: "03"
subsystem: autopilot
tags: [verify, ship, stage-runner, subprocess, evidence, VER-01, VER-02, VER-03, VER-05, VER-06, PERS-03]
dependency_graph:
  requires:
    - agentcouncil/autopilot/artifacts.py (VerifyArtifact, ShipArtifact, CommandEvidence, CriterionVerification, VerificationEnvironment, AcceptanceProbe)
    - agentcouncil/autopilot/run.py (AutopilotRun)
  provides:
    - agentcouncil/autopilot/verify.py (run_verify — StageRunner producing VerifyArtifact)
    - agentcouncil/autopilot/ship.py (run_ship — StageRunner producing ShipArtifact)
  affects:
    - agentcouncil/autopilot/orchestrator.py (consumes run_verify, run_ship via loader registry)
tech_stack:
  added: []
  patterns:
    - Real subprocess execution for command evidence (no test mocks at integration level)
    - Five-level verification dispatch (static/unit/integration/smoke/e2e)
    - importlib.util.find_spec for optional dependency detection
    - git subprocess calls with timeout protection for ship readiness
key_files:
  created:
    - agentcouncil/autopilot/verify.py
    - agentcouncil/autopilot/ship.py
    - tests/test_autopilot_verify.py
  modified: []
decisions:
  - execute_criterion dispatches by verification_level; e2e is gated on playwright availability
  - generate_probes returns empty list when test_commands exist — no interference with existing infra
  - run_verify computes overall_status=failed if any verdict is failed or blocked (skipped with skip_reason counts as OK)
  - run_ship uses real git subprocess calls; tests mock via patch for isolation
  - ShipArtifact rollback_plan always contains head_sha for deterministic revert command
metrics:
  duration: "~10 minutes"
  completed: "2026-04-15"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 0
---

# Phase 31 Plan 03: Verify and Ship Stage Runners Summary

**One-liner:** Five-level verify stage runner with real subprocess evidence collection and deterministic ship readiness packager, both matching StageRunner callable signature.

## What Was Built

### verify.py (VER-01 through VER-06)

`run_verify(run, registry, guidance) -> VerifyArtifact` — top-level stage runner that:

1. Calls `discover_verification_environment()` to detect project types, test commands, and Playwright availability via `importlib.util.find_spec`
2. Calls `generate_probes()` if no test commands detected, producing minimal test stubs per AcceptanceProbe
3. Calls `execute_criterion()` for each probe, dispatching by verification_level across five levels
4. Computes `overall_status` and `retry_recommendation` from aggregated verdicts
5. Returns `VerifyArtifact` with one `CriterionVerification` per probe (VER-03)

**`run_command(cmd, cwd, timeout)`** executes real subprocesses via `subprocess.run(shell=True)`, measures wall time, captures last 2000 chars of stdout/stderr, returns `CommandEvidence` with real exit codes. On timeout: exit_code=-1.

**`execute_criterion(probe, env, cwd)`** dispatch table:
- `static`: command_hint or first test_command
- `unit`: command_hint or first test_command  
- `integration`: command_hint priority, real subprocess (no mocks)
- `smoke`: command_hint or first health_check
- `e2e`: Playwright gate — skips with `skip_reason` when `playwright_available=False`

Failed verdicts get `failure_diagnosis` and `revision_guidance`. Skipped verdicts get `skip_reason` (satisfying VerifyArtifact model_validator).

### ship.py (PERS-03)

`run_ship(run, registry, guidance) -> ShipArtifact` — top-level stage runner that:

1. Calls `_get_git_info()` to get branch_name and head_sha via git subprocess
2. Calls `_check_worktree_clean()` to verify clean working tree
3. Determines `tests_passing` and `acceptance_criteria_met` from VerifyArtifact
4. Sets `recommended_action="ship"` when all conditions met, `"hold"` otherwise with `remaining_risks`
5. Builds `release_notes` from BuildArtifact files/commits
6. Sets `rollback_plan=f"git revert {head_sha}"` (always non-empty)

ShipArtifact model_validator constraints respected: ship requires clean state + tests passing + empty blockers + non-empty rollback_plan.

## Tests

29 tests in `tests/test_autopilot_verify.py`:

- `TestRunCommand` (4 tests): real subprocess execution, stdout capture, CommandEvidence return
- `TestDiscoverVerificationEnvironment` (3 tests): Playwright detection via mocked find_spec
- `TestExecuteCriterion` (5 tests): command_hint dispatch, e2e skip path, failed verdict fields
- `TestGenerateProbes` (3 tests): stub generation, empty return when commands exist
- `TestRunVerify` (8 tests): per-criterion evidence, overall_status logic, playwright skipping
- `TestRunShip` (6 tests): ship/hold paths, git info population, release notes/rollback

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all implementations are functional, not placeholder.

## Self-Check: PASSED
