---
name: autopilot
description: Run the AgentCouncil autopilot pipeline. Validates a spec via autopilot_prepare, then Claude follows proven workflow recipes to plan and build the work, then the orchestrator handles verify and ship through real runners and gate logic.
allowed-tools: mcp__agentcouncil__autopilot_prepare mcp__agentcouncil__autopilot_start mcp__agentcouncil__autopilot_status mcp__agentcouncil__autopilot_resume
argument-hint: [what to build — describe the feature, fix, or change]
---

# AgentCouncil Autopilot

You are running the AgentCouncil autopilot workflow. The pipeline validates your spec, classifies the work tier, then you plan and build the work following proven workflow recipes. The orchestrator runs verify and ship through real runners and gate logic.

**Intent:** $ARGUMENTS

## Protocol — follow these steps exactly

### Step 1: Understand the intent

Read the user's intent. If it's vague, ask 1-2 clarifying questions. You need enough to build a spec:
- What is being built/changed?
- What files are likely affected?
- What does "done" look like?

If the intent is already clear, proceed.

### Step 2: Build the spec

From the intent, construct:
- **spec_id**: Short kebab-case identifier (e.g., `add-backtester`, `fix-auth-timeout`)
- **title**: One-line title
- **objective**: 1-2 sentence description
- **requirements**: List of specific things that must be built/changed
- **acceptance_criteria**: List of verifiable conditions (e.g., "tests pass", "file contains X")
- **target_files**: Files likely created or modified (paths with `auth/`, `migrations/`, `infra/`, `deploy/`, `permissions/` trigger tier 3)
- **tier**: 1 (low-risk), 2 (standard, default), or 3 (sensitive)

Display the spec:

```
## Autopilot Spec

**ID:** {spec_id}
**Title:** {title}
**Objective:** {objective}
**Tier:** {tier}

**Requirements:**
- {each requirement}

**Acceptance Criteria:**
- {each criterion}

**Target Files:**
- {each file}
```

Ask: "Start with this spec?"

### Step 3: Validate and register the run

Call `mcp__agentcouncil__autopilot_prepare` with all spec fields.

This validates the spec (Pydantic model checks), classifies the tier from target_files, and persists the run. Save the returned `run_id` and the full `SpecPrepArtifact` (spec, research findings, clarifications).

Display:
```
Spec validated. Run: {run_id}
Tier: {tier} ({reason})

Now planning...
```

### Step 4: Plan (follow the plan workflow recipe)

Read `agentcouncil/autopilot/workflows/plan/workflow.md` — this is the execution recipe for the plan stage.

Then follow the 5-step planning process from the recipe:

1. **Parse the spec completely** — read all requirements, acceptance criteria, non-goals, and research findings from the `SpecPrepArtifact`. Do not begin decomposing until the full spec is internalized.
2. **Identify natural decomposition boundaries** — data model changes before logic, interfaces before implementations, shared utilities before callers.
3. **Size and order tasks** — use the XS/S/M/L scale from the recipe. XL tasks are a planning failure — split them.
4. **Write acceptance probes** — every acceptance criterion from the spec must map to at least one `AcceptanceProbe`. Specify `verification_level`, `mock_policy`, and `expected_observation` for each.
5. **Write execution order and verification strategy** — `execution_order` lists all `task_id` values in run sequence. `verification_strategy` describes the overall test approach.

Produce a structured task breakdown matching the `PlanArtifact` shape:

```
## Plan: {spec_id}

**Verification Strategy:** {narrative}

**Tasks:**
| Task ID | Title | Complexity | Depends On | Target Files |
|---------|-------|------------|------------|--------------|
| task-01 | ...   | small/medium/large | — | ... |
| task-02 | ...   | ...        | task-01    | ... |

**Acceptance Probes:**
| Probe ID | Criterion | Level | Mock Policy | Expected Observation |
|----------|-----------|-------|-------------|----------------------|
| probe-01 | ac-0: ... | unit  | forbidden   | ... |

**Execution Order:** task-01, task-02, ...
```

Display the plan and ask: "Proceed with this plan?"

Wait for confirmation before starting build.

### Step 5: Build (follow the build workflow recipe per task)

Read `agentcouncil/autopilot/workflows/build/workflow.md` — this is the execution recipe for the build stage.

For each task in `execution_order`, follow the increment cycle from the recipe:

**Implement:** Make the minimal change required. Touch only `task.target_files` unless new evidence demands otherwise. If you must touch additional files, document them in evidence.

**Test:** Run test commands covering this task. Do not advance to the next task if tests fail. Fix the implementation, not the tests.

**Verify:** Check the task's own `acceptance_criteria`. Run the `AcceptanceProbe.command_hint` for related probes where applicable.

**Commit:** Make a focused commit containing only this task's changes. Format: `{type}({scope}): {description}` where type is `feat`/`fix`/`test`/`refactor`/`chore`. Record the SHA.

**Record Evidence:** Produce a `BuildEvidence` entry with:
- `task_id` — the task just completed
- `files_changed` — every file touched
- `test_results` — test output summary
- `verification_notes` — how the task's acceptance criteria were checked

Follow these rules from the build recipe:
- **Rule 0:** One task at a time. Do not start task N+1 until task N has a green test run and a commit.
- **Rule 1:** The plan is the contract. Do not silently expand scope.
- **Rule 2:** Tests travel with the code. New behavior requires new tests.
- **Rule 3:** Never commit broken tests.
- **Rule 4:** Evidence is not optional. Empty `verification_notes` will cause the verify stage to treat the task as unverified.
- **Rule 5:** Commit SHAs are the audit trail. Record every SHA.

After all tasks complete, display a build summary:

```
## Build Summary

**Spec:** {spec_id}
**Run:** {run_id}

| Task | Commit | Files Changed | Tests |
|------|--------|---------------|-------|
| task-01: {title} | {sha} | {files} | ✅ / ❌ |
| task-02: {title} | {sha} | {files} | ✅ / ❌ |

All tests passing: ✅ / ❌
```

### Step 6: Verify and ship (via orchestrator)

After build is complete, call `mcp__agentcouncil__autopilot_start` with the `run_id`.

The verify and ship stages run through the orchestrator pipeline with real runners and gate logic. These stages consume the `BuildArtifact` evidence you produced and run the acceptance probes you defined in the plan. You do not need to implement them manually.

Display the final run status returned by the orchestrator.

## Rules

- Always show the spec before starting — let the user confirm before calling `autopilot_prepare`
- Always show the plan before building — let the user confirm the task breakdown before starting build
- Follow the workflow recipes — they are proven engineering patterns
- The plan is your contract — do not silently expand scope
- Evidence is mandatory — every task needs `files_changed`, `test_results`, `verification_notes`
- Verify every acceptance criterion — do not claim done without evidence
- If the spec is wrong, tell the user before planning — do not build the wrong thing

## Verify and Ship

After build, `autopilot_start` runs the verify and ship stages through the orchestrator with real runners and gate logic. Verify consumes the `BuildArtifact` evidence and runs the acceptance probes defined in the plan. Ship packages the verified output for release. These stages are fully automated — Claude does not implement them manually.
