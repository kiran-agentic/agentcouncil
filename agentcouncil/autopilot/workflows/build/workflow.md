<!--
Originally from: https://github.com/addyosmani/agent-skills
Path: skills/incremental-implementation/SKILL.md
License: MIT (Addy Osmani, 2025)
Copied: 2026-04-15, commit bf2fa6994407c9c888fc19a03fd54957991cfa0e
Modified for AgentCouncil autopilot integration
-->

# Build Stage Workflow

The build stage executes the task breakdown from `PlanArtifact`, producing a `BuildArtifact` containing per-task implementation evidence, commit SHAs, and aggregate test results.

Build in thin vertical slices — implement one piece, test it, verify it, then expand. Each increment should leave the system in a working, testable state. This is the execution discipline that makes large features manageable.

## The Increment Cycle

For each task in `execution_order`:

```
┌──────────────────────────────────────┐
│                                      │
│   Implement ──→ Test ──→ Verify ──┐  │
│       ▲                           │  │
│       └───── Commit ◄─────────────┘  │
│              │                       │
│              ▼                       │
│       Record Evidence                │
│              │                       │
│              ▼                       │
│          Next task                   │
│                                      │
└──────────────────────────────────────┘
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

**Checkpoint:** After evidence is recorded, call `autopilot_checkpoint` with
`protocol_step="building"`, `stage="build"`, and `stage_status="in_progress"`.
This makes the next incomplete task recoverable after context compaction.

## Slicing Strategies

### Vertical Slices (Preferred)

Build one complete path through the stack:

```
Slice 1: Create a task (DB + API + basic UI)
    → Tests pass, user can create a task via the UI

Slice 2: List tasks (query + API + UI)
    → Tests pass, user can see their tasks

Slice 3: Edit a task (update + API + UI)
    → Tests pass, user can modify tasks

Slice 4: Delete a task (delete + API + UI + confirmation)
    → Tests pass, full CRUD complete
```

Each slice delivers working end-to-end functionality.

### Contract-First Slicing

When backend and frontend need to develop in parallel:

```
Slice 0: Define the API contract (types, interfaces, OpenAPI spec)
Slice 1a: Implement backend against the contract + API tests
Slice 1b: Implement frontend against mock data matching the contract
Slice 2: Integrate and test end-to-end
```

### Risk-First Slicing

Tackle the riskiest or most uncertain piece first:

```
Slice 1: Prove the WebSocket connection works (highest risk)
Slice 2: Build real-time task updates on the proven connection
Slice 3: Add offline support and reconnection
```

If Slice 1 fails, you discover it before investing in Slices 2 and 3.

## Implementation Rules

**Rule 0: Simplicity first.**

Before writing any code, ask: "What is the simplest thing that could work?"

After writing code, review it against these checks:
- Can this be done in fewer lines?
- Are these abstractions earning their complexity?
- Would a staff engineer look at this and say "why didn't you just..."?
- Am I building for hypothetical future requirements, or the current task?

```
SIMPLICITY CHECK:
✗ Generic EventBus with middleware pipeline for one notification
✓ Simple function call

✗ Abstract factory pattern for two similar components
✓ Two straightforward components with shared utilities

✗ Config-driven form builder for three forms
✓ Three form components
```

Three similar lines of code is better than a premature abstraction. Implement the naive, obviously-correct version first. Optimize only after correctness is proven with tests.

**Rule 1: Scope discipline.**

Touch only what the task requires.

Do NOT:
- "Clean up" code adjacent to your change
- Refactor imports in files you're not modifying
- Remove comments you don't fully understand
- Add features not in the spec because they "seem useful"
- Modernize syntax in files you're only reading

If you notice something worth improving outside your task scope, note it — don't fix it:

```
NOTICED BUT NOT TOUCHING:
- src/utils/format.ts has an unused import (unrelated to this task)
- The auth middleware could use better error messages (separate task)
```

**Rule 2: One task at a time.**

Do not start task N+1 until task N has a green test run and a commit. Multi-task changes corrupt the evidence trail.

Each increment changes one logical thing. Don't mix concerns:

**Bad:** One commit that adds a new component, refactors an existing one, and updates the build config.

**Good:** Three separate commits — one for each change.

**Rule 3: The plan is the contract.**

The task breakdown is the agreed contract. If the implementation requires changes to other files not in `target_files`, record them in evidence but do not silently expand scope. If significant new scope is discovered, document it in `verification_notes` so the review gate can assess impact.

**Rule 4: Tests travel with the code.**

New behavior requires new tests. New tests must cover the new behavior, not just exist. If the task adds a function, the test verifies the function's actual behavior. Trivial tests are worse than no tests — they create false confidence.

**Rule 5: Never commit broken tests.**

Broken tests are debt with interest. A commit with a failing test is not evidence — it is anti-evidence. If a test is temporarily broken during refactoring, stash or comment it, fix it, then commit.

After each increment, the project must build and existing tests must pass. Don't leave the codebase in a broken state between slices.

**Rule 6: Evidence is not optional.**

The verify stage consumes `BuildArtifact.evidence`. Evidence entries with empty `verification_notes` will cause verify to treat the task as unverified. Write honest notes, even negative ones ("no test coverage for this path because X").

**Rule 7: Commit SHAs are audit trail.**

Record every commit SHA in `BuildArtifact.commit_shas`. These are used by the ship stage to construct release notes and identify the diff since the last release.

## Increment Checklist

Before marking a task done:

- [ ] All tests that were passing before this task are still passing
- [ ] At least one test covers the new behavior (if behavior-changing)
- [ ] The commit message accurately describes what changed
- [ ] `BuildEvidence` entry created with `files_changed`, `test_results`, `verification_notes`
- [ ] `autopilot_checkpoint` called after evidence is recorded
- [ ] Files touched match `task.target_files` (or deviation is documented)
- [ ] No debug code, print statements, or TODO comments left in production paths
- [ ] The change does one thing and does it completely

## Final Build Handoff

After the last task:

- [ ] Produce a valid `BuildArtifact` with non-empty evidence
- [ ] Confirm `all_tests_passing` is accurate
- [ ] Record aggregate `files_changed` and `commit_shas`
- [ ] Call `autopilot_checkpoint` with `protocol_step="build_complete"`, `stage="build"`, `stage_status="gated"`, `required_tool="review_loop"`, and `next_required_action="Run the build review gate before verification."`
- [ ] Run the build `review_loop` gate before any verify work

Do not start verification until the build review gate has passed and
`autopilot_checkpoint` has recorded `protocol_step="build_review_passed"`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll test it all at the end" | Bugs compound. A bug in Slice 1 makes Slices 2-5 wrong. Test each slice. |
| "It's faster to do it all at once" | It *feels* faster until something breaks and you can't find which of 500 changed lines caused it. |
| "These changes are too small to commit separately" | Small commits are free. Large commits hide bugs and make rollbacks painful. |
| "This refactor is small enough to include" | Refactors mixed with features make both harder to review and debug. Separate them. |
| "I'll figure out the tests later" | Tests written after the fact test what you built, not what you should have built. |

## Red Flags in Build

Stop and reassess if:
- A task requires touching more files than planned and none of them are in `target_files`
- Tests are being changed to make them pass rather than fixing the implementation
- A task has been "in progress" for more than one complete increment cycle
- Test results are inconsistent (passes sometimes, fails sometimes) — flakiness is a build blocker
- A required service (database, API) is unavailable — do not paper over with mocks at integration level
- The implementation fundamentally contradicts the plan's approach — this requires a plan revision gate, not a silent pivot
- More than 100 lines of code written without running tests
- Multiple unrelated changes in a single increment
- "Let me just quickly add this too" scope expansion
- Building abstractions before the third use case demands it
- Creating new utility files for one-time operations

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
