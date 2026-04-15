---
phase: 28-gate-normalization-layer
plan: "01"
subsystem: autopilot/normalizer
tags: [tdd, gate-normalization, orchestrator, artifacts]
dependency_graph:
  requires:
    - agentcouncil/schemas.py (ConsensusArtifact, ReviewArtifact, ConvergenceResult, ChallengeArtifact, DecideArtifact)
    - agentcouncil/autopilot/artifacts.py (GateDecision)
  provides:
    - agentcouncil/autopilot/normalizer.py (GateNormalizer)
  affects:
    - agentcouncil/autopilot/__init__.py (re-exports GateNormalizer)
tech_stack:
  added: []
  patterns:
    - TDD red/green with pytest
    - Pydantic BaseModel with use_enum_values pitfall (str comparisons, not enum members)
    - Wildcard re-export pattern matching existing autopilot package conventions
key_files:
  created:
    - agentcouncil/autopilot/normalizer.py
    - tests/test_autopilot_normalizer.py
  modified:
    - agentcouncil/autopilot/__init__.py
decisions:
  - "ConsensusArtifact.status compared as string literals not enum members due to use_enum_values=True"
  - "Top-level try/except in normalize() converts all errors to block decisions"
  - "revision_guidance from high/critical findings first, then all findings, then fallback"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-15"
  tasks: 2
  files: 3
---

# Phase 28 Plan 01: Gate Normalization Layer Summary

**One-liner:** GateNormalizer class with normalize() mapping all 5 protocol output types (ConsensusArtifact, ReviewArtifact, ConvergenceResult, ChallengeArtifact, DecideArtifact) to uniform GateDecision (advance/revise/block) using TDD with 22 tests.

## What Was Built

`agentcouncil/autopilot/normalizer.py` — The translation layer between protocol-specific outputs and the orchestrator's uniform gate contract. The orchestrator (Phase 30) will call `GateNormalizer().normalize(protocol_type, artifact)` and act on the returned `GateDecision` without ever branching on protocol type.

Key behaviors implemented per normalization table (AUTOPILOT-ROADMAP Section 3.8):

| Protocol | advance | revise | block |
|----------|---------|--------|-------|
| brainstorm | consensus, consensus_with_reservations | — (no revise path) | unresolved_disagreement, partial_failure |
| review | pass | revise (guidance from findings) | escalate |
| review_loop | pass | revise (guidance from final_findings) | escalate |
| challenge | ready | needs_hardening (guidance from must_harden modes) | not_ready |
| decide | decided | experiment (guidance = experiment_plan) | deferred |

Error handling: top-level try/except catches all exceptions and returns `decision="block"` with descriptive rationale — never raises.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for GateNormalizer | 4907986 | tests/test_autopilot_normalizer.py |
| 1 (GREEN) | Implement GateNormalizer | 08f329b | agentcouncil/autopilot/normalizer.py |
| 2 | Package re-export and full suite validation | 05b1f6d | agentcouncil/autopilot/__init__.py |

## Test Results

- 22 tests in `tests/test_autopilot_normalizer.py` — all pass
- Full suite: 790 passed, 12 deselected, 19 warnings — 0 regressions

## Deviations from Plan

None — plan executed exactly as written.

Notable implementation detail: `_guidance_from_findings()` first collects high/critical severity findings; if none, falls back to all findings descriptions; if still empty, uses the provided fallback string. This correctly handles the `test_review_revise_fallback_to_next_action` test case where findings list is empty.

## Known Stubs

None.

## Self-Check: PASSED

Files exist:
- agentcouncil/autopilot/normalizer.py — FOUND
- tests/test_autopilot_normalizer.py — FOUND

Commits exist:
- 4907986 — test(28-01): add failing tests for GateNormalizer — FOUND
- 08f329b — feat(28-01): implement GateNormalizer — FOUND
- 05b1f6d — feat(28-01): re-export GateNormalizer from autopilot package — FOUND
