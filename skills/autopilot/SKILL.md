---
name: autopilot
description: Run the AgentCouncil autopilot pipeline. Validates a spec, classifies tier, then YOU (Claude) implement the work using the spec as your contract. Use when you want structured spec validation and tier classification before implementing a feature.
allowed-tools: mcp__agentcouncil__autopilot_prepare mcp__agentcouncil__autopilot_start mcp__agentcouncil__autopilot_status mcp__agentcouncil__autopilot_resume
argument-hint: [what to build — describe the feature, fix, or change]
---

# AgentCouncil Autopilot

You are running the AgentCouncil autopilot workflow. The pipeline validates your spec and classifies the work tier. Then YOU implement the work — the pipeline's plan/build stages are stubs in v2.0 and cannot write code.

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

This validates the spec (Pydantic model checks), classifies the tier from target_files, and persists the run. Save the returned `run_id`.

Display:
```
Spec validated. Run: {run_id}
Tier: {tier} ({reason})

Now implementing...
```

### Step 4: Implement the work yourself

**You are the builder.** Use the spec as your contract:
- Read existing code to understand the codebase
- Implement each requirement from the spec
- Create/modify the target files
- Follow project conventions (read CLAUDE.md if it exists)
- Commit each logical change atomically

Work through the requirements one by one. After each, check it against the acceptance criteria.

### Step 5: Verify against acceptance criteria

After implementation, verify EVERY acceptance criterion from the spec:
- Run tests if applicable
- Check files exist with expected content
- Verify imports work
- Run any commands specified in the criteria

Display results:
```
## Verification

| Criterion | Status |
|-----------|--------|
| {criterion 1} | ✅ / ❌ |
| {criterion 2} | ✅ / ❌ |
```

If any fail, fix them before proceeding.

### Step 6: Update run status

Call `mcp__agentcouncil__autopilot_status` with the `run_id` to confirm the run is tracked.

Display:
```
## Autopilot Complete

**Run:** {run_id}
**Spec:** {spec_id}
**Tier:** {tier}

**Implemented:**
- {summary of what was built}

**Verified:**
- {count} acceptance criteria passed
```

## Rules

- Always show the spec before starting — let the user confirm
- The pipeline validates the spec and classifies tier — that's its job in v2.0
- YOU do the actual implementation — plan/build stages are stubs
- Verify every acceptance criterion — don't claim done without evidence
- Commit changes atomically as you go
- If the spec is wrong, tell the user before implementing — don't build the wrong thing

## Why Not Run the Full Pipeline?

The `autopilot_start` tool runs all 5 stages, but `plan` and `build` produce stub artifacts — they don't write code. Running the full pipeline gives a false "completed" status without any real work done. In v2.0, use `autopilot_prepare` for spec validation + tier classification, then implement directly.

When real plan/build runners ship in a future version, this skill will switch to running the full pipeline.
