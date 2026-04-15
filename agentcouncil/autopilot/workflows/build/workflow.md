<!--
Originally from: https://github.com/addyosmani/agent-skills
Path: skills/incremental-implementation/SKILL.md
License: MIT (Addy Osmani, 2025)
Copied: 2026-04-15, commit bf2fa6994407c9c888fc19a03fd54957991cfa0e
Modified for AgentCouncil autopilot integration
-->

# Build Stage Workflow

The build stage executes the task breakdown from `PlanArtifact`, producing a `BuildArtifact` containing per-task implementation evidence, commit SHAs, and aggregate test results.

## The Increment Cycle

For each task in `execution_order`:

```
Implement → Test → Verify → Commit → Record Evidence
```

**Implement:** Make the minimal change required by the task. Touch only the files in `task.target_files` unless new evidence demands otherwise. If new files must be created that were not in the plan, note them in `BuildEvidence.verification_notes`.

**Test:** Run the test commands that cover this task. Do not advance to the next task if tests fail. If tests fail, fix the implementation, not the tests. Exception: if the test itself is wrong (spec changed, test tests the wrong thing), document the fix.

**Verify:** Check that the task's own acceptance criteria are met. Each task carries `acceptance_criteria` — verify them manually or by running the probe hints from `AcceptanceProbe.command_hint` for related probes.

**Commit:** Make a focused commit containing only this task's changes. Commit message format: `{type}({scope}): {description}` where type is feat/fix/test/refactor/chore. Record the SHA.

**Record Evidence:** Produce a `BuildEvidence` entry with:
- `task_id` — the task just completed
- `files_changed` — every file touched
- `test_results` — test output summary
- `verification_notes` — how the task's acceptance criteria were checked

## Implementation Rules

**Rule 0: One task at a time.**
Do not start task N+1 until task N has a green test run and a commit. Multi-task changes corrupt the evidence trail.

**Rule 1: The plan is the contract.**
The task breakdown is the agreed contract. If the implementation requires changes to other files not in `target_files`, record them in evidence but do not silently expand scope. If significant new scope is discovered, document it in `verification_notes` so the review gate can assess impact.

**Rule 2: Tests travel with the code.**
New behavior requires new tests. New tests must cover the new behavior, not just exist. If the task adds a function, the test verifies the function's actual behavior. Trivial tests are worse than no tests — they create false confidence.

**Rule 3: Never commit broken tests.**
Broken tests are debt with interest. A commit with a failing test is not evidence — it is anti-evidence. If a test is temporarily broken during refactoring, stash or comment it, fix it, then commit.

**Rule 4: Evidence is not optional.**
The verify stage consumes `BuildArtifact.evidence`. Evidence entries with empty `verification_notes` will cause verify to treat the task as unverified. Write honest notes, even negative ones ("no test coverage for this path because X").

**Rule 5: Commit SHAs are audit trail.**
Record every commit SHA in `BuildArtifact.commit_shas`. These are used by the ship stage to construct release notes and identify the diff since the last release.

## Increment Checklist

Before marking a task done:

- [ ] All tests that were passing before this task are still passing
- [ ] At least one test covers the new behavior (if behavior-changing)
- [ ] The commit message accurately describes what changed
- [ ] `BuildEvidence` entry created with `files_changed`, `test_results`, `verification_notes`
- [ ] Files touched match `task.target_files` (or deviation is documented)
- [ ] No debug code, print statements, or TODO comments left in production paths

## Red Flags in Build

Stop and reassess if:
- A task requires touching more files than planned and none of them are in `target_files`
- Tests are being changed to make them pass rather than fixing the implementation
- A task has been "in progress" for more than one complete increment cycle
- Test results are inconsistent (passes sometimes, fails sometimes) — flakiness is a build blocker
- A required service (database, API) is unavailable — do not paper over with mocks at integration level
- The implementation fundamentally contradicts the plan's approach — this requires a plan revision gate, not a silent pivot

## BuildArtifact Schema Reference

The build stage must produce a valid `BuildArtifact`:

```
BuildArtifact:
  build_id        — unique identifier (e.g., "build-abc1234")
  plan_id         — from PlanArtifact.plan_id (traceability)
  spec_id         — from PlanArtifact.spec_id (traceability)
  evidence        — list[BuildEvidence] (non-empty, one per task minimum)
  all_tests_passing — true only if all test suites green at end of build
  files_changed   — aggregate list of all files modified across all tasks
  commit_shas     — list of git commit SHAs produced during build

BuildEvidence:
  task_id         — which plan task this covers
  files_changed   — paths modified for this task
  test_results    — test output summary (or "no tests ran" with reason)
  verification_notes — how this task's acceptance criteria were checked
```
