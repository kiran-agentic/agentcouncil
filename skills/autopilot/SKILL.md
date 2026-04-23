---
name: autopilot
description: Council-governed autonomous delivery. Claude follows workflow recipes to plan and build; independent agents review at every stage transition. The full pipeline — spec, plan, build, verify, ship — with review loops and conditional challenge gates.
allowed-tools: mcp__agentcouncil__autopilot_prepare mcp__agentcouncil__autopilot_start mcp__agentcouncil__autopilot_status mcp__agentcouncil__autopilot_resume mcp__agentcouncil__review_loop mcp__agentcouncil__challenge
argument-hint: [what to build — describe the feature, fix, or change]
---

# AgentCouncil Autopilot

You are running the AgentCouncil autopilot pipeline — council-governed autonomous software delivery. You follow proven workflow recipes to plan and build. An independent agent reviews your work at every stage transition. No single agent's judgment goes unchecked.

**Intent:** $ARGUMENTS

**Pipeline:**
```
spec_prep → REVIEW_LOOP → plan → REVIEW_LOOP → build → REVIEW_LOOP → verify → CHALLENGE? → ship
```

## Protocol — follow these steps exactly

### Step 0: Set escalation level and read existing conventions

Send the user **one message** containing both of the following. Do not proceed until you have the answer to item (1).

**1. Escalation level** — ask:

> "How should I handle unknowns during this run?
> - **`minimal`**: interrupt only for critical blockers — security risks, potential data loss, or scope changes that could be destructive
> - **`normal`** (default): interrupt when the wrong assumption would require significant rework of the spec or plan
> - **`verbose`**: ask about anything uncertain before proceeding
>
> Reply with `minimal`, `normal`, or `verbose` (or just press Enter for `normal`)."

Record the answer as `ESCALATION_LEVEL`. Default to `normal` if the user presses Enter or gives no answer.

**2. Read existing project conventions** — before writing the spec, read these files if they exist (they bound your spec and test strategy):
- `pyproject.toml` — test runner (`[tool.pytest.ini_options]`), lint config (`[tool.ruff]` or `[tool.mypy]`), build commands
- `pytest.ini` or `setup.cfg` — alternate pytest config
- `.ruff.toml` — alternate ruff config
- `Makefile` — `test`, `lint`, `build` targets

Note: (a) the test command to use in build steps, (b) the lint/type-check command if configured, (c) where tests live.

**Critical unknowns always escalate regardless of `ESCALATION_LEVEL`:** security risks, destructive scope (deleting data, breaking APIs), or requirements that contradict each other. For all other unknowns, apply the level the user set.

### Step 1: Understand the intent

Read the user's intent. Before writing the spec, list the technical assumptions you are making — about the tech stack, framework, auth model, data storage, deployment target, and any conventions you read in Step 0. Present them as:

```
ASSUMPTIONS:
1. [assumption]
2. [assumption]
→ Correct me now or I'll proceed with these.
```

If the intent is genuinely vague (target unclear, scope undefined), ask 1-2 clarifying questions in the same message as your assumptions. Batch everything — one message.

### Step 2: Build the spec

From the intent, construct:
- **spec_id**: Short kebab-case identifier (e.g., `add-backtester`, `fix-auth-timeout`)
- **title**: One-line title
- **objective**: 1-2 sentence description
- **requirements**: List of specific things that must be built/changed
- **acceptance_criteria**: List of verifiable conditions (e.g., "tests pass", "file contains X")
- **target_files**: Files likely created or modified (paths with `auth/`, `migrations/`, `infra/`, `deploy/`, `permissions/` trigger tier 3)
- **testing_strategy**: Test framework (from Step 0), test locations, expected test types for this change (unit/integration/e2e). Example: "pytest, tests/ dir, unit tests for logic, one integration test for the API endpoint."
- **behavioral_boundaries**:
  - *Always*: actions you will always take (e.g., "run tests before commit", "validate all user inputs")
  - *Ask first*: actions that need approval (e.g., "schema changes", "adding new dependencies")
  - *Never*: prohibited actions (e.g., "modify files outside target_files without documenting", "skip failing tests")
- **tier**: 1 (low-risk), 2 (standard, default), or 3 (sensitive)

Display the spec, then proceed immediately to validation. Do not wait for user confirmation — autopilot is autonomous.

### Step 3: Validate and register the run

Write the spec to disk before registering. Create the file `docs/autopilot/specs/{spec_id}.md` with the full spec content formatted as markdown. This persists the spec for future reference independent of this conversation.

Call `mcp__agentcouncil__autopilot_prepare` with all spec fields, plus `escalation_level=ESCALATION_LEVEL`.

Save the returned `run_id` and `tier`. Display:
```
Spec validated. Run: {run_id}
Tier: {tier} ({reason})
```

### Step 4: Gate — review the spec

Call `mcp__agentcouncil__review_loop` to get independent review of the spec:
- **artifact**: The full spec text (requirements, acceptance criteria, target files, constraints)
- **artifact_type**: `"plan"`
- **review_objective**: `"Review this spec for completeness, feasibility, and risk before planning begins"`
- **focus_areas**: `["requirements clarity", "acceptance criteria testability", "testing strategy completeness", "behavioral boundaries defined", "scope boundaries", "missing edge cases"]`

**Handle the gate decision from `final_verdict`:**
- **`pass`** → proceed to Step 5
- **`revise`** → read the `final_findings`, fix the spec, display changes, and re-run this gate (max 2 revisions, then ask user)
- **`escalate`** → display findings, stop, and ask the user how to proceed

### Step 5: Plan (follow the plan workflow recipe)

Read `agentcouncil/autopilot/workflows/plan/workflow.md` — this is the execution recipe.

**Read-only mode:** Do not write or modify any code during this step. The output is a plan document, not implementation.

Follow the 5-step planning process:

1. **Parse the spec completely** — all requirements, acceptance criteria, non-goals, research findings. Do not decompose until fully internalized.
2. **Identify natural decomposition boundaries** — schema before logic, interfaces before implementations, shared utilities before callers.
3. **Size and order tasks** — XS/S/M/L scale. XL = split it.
4. **Write acceptance probes** — every acceptance criterion maps to at least one probe. Specify `verification_level`, `mock_policy`, `expected_observation`.
5. **Write execution order and verification strategy**.

Display the plan:

```
## Plan: {spec_id}

**Verification Strategy:** {narrative}

| Task ID | Title | Complexity | Depends On | Target Files | Verification |
|---------|-------|------------|------------|--------------|--------------|
| task-01 | ...   | small      | —          | ...          | `pytest tests/path/test_foo.py` passes |

| Probe ID | Criterion | Level | Mock Policy | Expected Observation |
|----------|-----------|-------|-------------|----------------------|
| probe-01 | ac-0: ... | unit  | forbidden   | ...                  |

**Execution Order:** task-01, task-02, ...

**Risks and Mitigations:**
| Risk | Severity | Mitigation |
|------|----------|------------|
| [risk from spec gate findings] | high/medium/low | [what you'll do if it materialises] |
```

### Step 6: Gate — review the plan (MANDATORY)

**DO NOT SKIP THIS STEP.** The plan must be independently reviewed before any code is written. This is a non-negotiable gate.

Call `mcp__agentcouncil__review_loop`:
- **artifact**: The full plan text (tasks, probes, execution order, verification strategy)
- **artifact_type**: `"plan"`
- **review_objective**: `"Review this implementation plan for completeness, ordering, risk, and verification coverage"`
- **focus_areas**: `["task decomposition", "dependency ordering", "acceptance probe coverage", "scope creep"]`

**Handle the gate decision:**
- **`pass`** → proceed to Step 7 (do NOT ask the user for confirmation — autopilot is autonomous)
- **`revise`** → read findings, revise the plan, display changes, re-run this gate (max 2 revisions)
- **`escalate`** → display findings, stop, ask user

**If the review_loop tool fails or is unavailable, STOP and tell the user. Do not proceed to build without a reviewed plan.**

### Step 7: Build (follow the build workflow recipe per task)

Read `agentcouncil/autopilot/workflows/build/workflow.md` — this is the execution recipe.

For each task in `execution_order`, follow the increment cycle:

**Write test first (RED):** Before writing any implementation code, write a test that expresses the expected behavior. Run it — it must FAIL. A test that passes immediately proves nothing.

**Implement (GREEN):** Write the minimal code to make the failing test pass. Ask: "What is the simplest thing that could work?" Do not over-engineer. Three similar lines of code is better than a premature abstraction.

**Confirm (PASS):** Run the test. It must pass. If it doesn't, fix the implementation — not the test.

**Refactor:** With the test green, clean up the implementation without changing behavior. Run tests after any refactor step.

**Verify:** Check the task's `acceptance_criteria` are met beyond what the test directly covers.

**Commit:** Focused commit: `{type}({scope}): {description}`. Record the SHA.

**Bug-fix tasks — prove-it pattern (REQUIRED):** For any task that fixes a bug:
1. Write a test that reproduces the bug. Run it — it must FAIL (confirming the bug exists).
2. Implement the fix.
3. Run the test — it must PASS (confirming the fix works).
4. Run the full test suite — no new failures (regression guard).

A bug fix without a reproduction test is not complete.

**Record Evidence:** For each task, note:
- `task_id` — the task completed
- `files_changed` — every file touched
- `test_results` — test output summary
- `verification_notes` — how acceptance criteria were checked

Build rules (from the recipe):
- **Rule 0: Simplicity first** — after implementing, ask: "Could this be fewer lines? Am I building for hypothetical future requirements?" Write the naive, obviously-correct version first.
- **Rule 0.5: Scope discipline** — touch only `task.target_files`. If you notice something worth improving outside scope, note it — don't fix it.
- **Rule 1: The plan is the contract** — no silent scope expansion
- **Rule 2: Tests travel with the code** — unit tests for logic, integration tests for API/DB boundaries, E2E tests only for critical user flows. Aim for ~80% unit / ~15% integration / ~5% E2E.
- **Rule 3: Never commit broken tests**
- **Rule 4: Evidence is not optional**
- **Rule 5: Commit SHAs are the audit trail** — each commit should be independently revertable (additive changes before deletions; avoid mixing logic change + format change in one commit)
- **Rule 6: Safe defaults** — new code defaults to conservative behavior (disabled flags, allowlists not blocklists, strict validation). Especially in tier 3 runs.
- **Rule 7: Feature flags for incomplete slices** — if a task lands user-reachable but incomplete behavior, gate it behind a feature flag so the commit is safe to merge.
- **Rule 8: 100-line limit** — if you are about to write more than ~100 lines without running a test, stop and run the tests first.

**Regression self-check (every 3 tasks):** After completing every third task (task-03, task-06, task-09, ...), before continuing:
1. Run the **full test suite** (not just the current task's tests).
2. Confirm all previously-completed tasks' acceptance criteria still pass.
3. Confirm the build is clean.

If anything fails, fix it before continuing. This catches regressions while context is fresh, rather than at the final build gate.

After all tasks, display:

```
## Build Summary

| Task | Commit | Files Changed | Tests |
|------|--------|---------------|-------|
| task-01: {title} | {sha} | {files} | pass/fail |

All tests passing: yes/no
Total files changed: {list}
Commit SHAs: {list}
```

### Step 8: Gate — review the build (MANDATORY)

**DO NOT SKIP THIS STEP.** The build must be independently reviewed before verification. This is a non-negotiable gate.

Call `mcp__agentcouncil__review_loop`:
- **artifact**: A summary of all code changes. Include: the diff summary, per-task evidence (files_changed, test_results, verification_notes), and the list of commit SHAs.
- **artifact_type**: `"code"`
- **review_objective**: `"Review the implementation for correctness, quality, and spec compliance"`
- **focus_areas**: `["correctness", "test coverage", "spec compliance", "code quality", "security"]`

**Handle the gate decision:**
- **`pass`** → proceed to Step 9
- **`revise`** → read findings, fix the issues (follow the increment cycle for fixes), re-run this gate (max 2 revisions)
- **`escalate`** → display findings, stop, ask user

**If the review_loop tool fails or is unavailable, STOP and tell the user. Do not proceed to verify without a reviewed build.**

### Step 9: Verify

Run the acceptance probes you defined in the plan. For each probe:
- Execute the `command_hint` if specified
- Check the `expected_observation`
- Record pass/fail with evidence

Display:

```
## Verification

| Probe | Criterion | Level | Status | Evidence |
|-------|-----------|-------|--------|----------|
| probe-01 | ac-0: ... | unit | pass/fail | ... |

Overall: passed/failed
```

If any probes fail with `retry_recommendation = retry_build`, go back to Step 7 with revision guidance (max 2 retries).

### Step 10: Gate — challenge (conditional)

**Only run this gate if tier >= 3 OR target_files touch sensitive paths (auth/, migrations/, infra/, deploy/, permissions/).**

If the challenge gate should fire, call `mcp__agentcouncil__challenge`:
- **artifact**: The verification results + build evidence + spec
- **assumptions**: List of assumptions from the spec and plan
- **success_criteria**: The acceptance criteria from the spec
- **rounds**: 2

**Handle the gate decision from `artifact.readiness`:**
- **`ready`** → proceed to Step 11
- **`needs_hardening`** → read `failure_modes` where `disposition == "must_harden"`, fix the issues, re-run verify (Step 9), then re-run this gate
- **`not_ready`** → display failure modes, stop, ask user

If challenge is skipped (tier < 3, no sensitive paths), proceed directly to Step 11.

### Step 11: Ship

Display the final delivery summary:

```
## Autopilot Complete

**Run:** {run_id}
**Spec:** {spec_id}
**Tier:** {tier}

**Gates passed:**
- Spec review: {pass/revise count}
- Plan review: {pass/revise count}
- Build review: {pass/revise count}
- Challenge: {passed/skipped}

**Delivered:**
- {count} tasks completed
- {count} acceptance criteria verified
- {count} commits: {sha list}

**Files changed:**
- {file list}
```

## Gate Protocol

Every gate follows the same pattern:

1. **Call the protocol** — `review_loop` for spec/plan/build, `challenge` for post-verify
2. **Read the verdict** — `final_verdict` for review_loop, `readiness` for challenge
3. **Act on it:**
   - **advance** (pass/ready) → continue to next step
   - **revise** (revise/needs_hardening) → fix issues, re-run the gate (max 2 revisions per gate)
   - **block** (escalate/not_ready) → stop, display findings, ask the user

**On revision re-runs, pass `prior_review_context`.** When re-running a `review_loop` gate after a revision, pass the prior cycle's findings (formatted as a short summary including finding IDs, titles, severities, and your resolution notes) as the `prior_review_context` parameter. This focuses the reviewer on whether the revision actually resolved prior issues and whether it introduced new ones — instead of re-discovering the same terrain from scratch.

If a gate revision loop exceeds 2 iterations, stop and ask the user — do not loop forever.

## Rules

- Display the spec before calling `autopilot_prepare` — but do not wait for confirmation, proceed autonomously
- Display the plan before building — but do not wait for confirmation after the plan gate passes, proceed autonomously
- Follow the workflow recipes — read `plan/workflow.md` and `build/workflow.md`
- The plan is your contract — do not silently expand scope during build
- Evidence is mandatory — every task needs `files_changed`, `test_results`, `verification_notes`
- **Gates are NEVER optional** — every stage transition goes through independent review. Skipping a gate is a protocol violation. If a gate tool is unavailable, STOP — do not proceed without review.
- On `revise`, fix the specific findings — do not start over from scratch
- On `escalate`/`not_ready`, stop and involve the user — do not override the gate
- If the spec is wrong, say so before planning — do not build the wrong thing
