---
name: autopilot
description: Run the AgentCouncil autopilot pipeline. Sequences work through spec_prep → plan → build → verify → ship with typed artifacts, gate transitions, and persistent state. Use when you want to automate a multi-stage development workflow with verification gates.
allowed-tools: mcp__agentcouncil__autopilot_prepare mcp__agentcouncil__autopilot_start mcp__agentcouncil__autopilot_status mcp__agentcouncil__autopilot_resume
argument-hint: [what to build — describe the feature, fix, or change]
---

# AgentCouncil Autopilot

You are running the AgentCouncil autopilot pipeline. This sequences work through five stages with typed artifacts and gate transitions.

**Intent:** $ARGUMENTS

## Protocol — follow these steps exactly

### Step 1: Understand the intent

Read the user's intent. If it's vague, ask 1-2 clarifying questions before proceeding. You need enough to build a spec:
- What is being built/changed?
- What files are likely affected?
- What does "done" look like?

If the intent is already clear and specific, skip questions and proceed.

### Step 2: Build the spec

From the intent and any clarification, construct:
- **spec_id**: A short kebab-case identifier (e.g., `add-backtester`, `fix-auth-timeout`)
- **title**: One-line title
- **objective**: 1-2 sentence description of what this delivers
- **requirements**: List of specific things that must be built/changed
- **acceptance_criteria**: List of verifiable conditions that prove it's done (e.g., "tests pass", "endpoint returns 200", "file contains X")
- **target_files**: List of files likely to be created or modified (used for tier classification — paths containing `auth/`, `migrations/`, `infra/`, `deploy/`, or `permissions/` trigger tier 3)
- **tier**: 1 (low-risk), 2 (standard, default), or 3 (sensitive) — auto-classified from target_files but can be overridden

Display the spec to the user:

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

Ask: "Start the autopilot pipeline with this spec?"

### Step 3: Prepare the run

Call `mcp__agentcouncil__autopilot_prepare` with all spec fields.

Save the returned `run_id`.

Display:
```
Run created: {run_id}
Tier: {tier} ({tier_reason if available})
Starting pipeline...
```

### Step 4: Execute the pipeline

Call `mcp__agentcouncil__autopilot_start` with the `run_id`.

The pipeline sequences: `spec_prep → plan → build → verify → ship`

Display the result:
- If `status=completed`: Show the stage summary and congratulate
- If `status=paused_for_approval`: Show which stage needs approval and what's blocking
- If `status=paused_for_revision`: Show what needs revision
- If `status=failed`: Show the failure_reason and suggest next steps

### Step 5: Handle paused runs

If the run paused (approval or revision needed):

1. Show the user what's blocking:
   ```
   ## Pipeline Paused

   **Status:** {status}
   **Stage:** {current_stage}
   **Reason:** {failure_reason or "Approval required for this stage"}

   **Stages:**
   {for each stage: name — status (gate_decision if any)}
   ```

2. Ask: "Resume the pipeline?" or "Check status first?"

3. If resume: Call `mcp__agentcouncil__autopilot_resume` with the `run_id`
4. If status: Call `mcp__agentcouncil__autopilot_status` with the `run_id`, display, then ask again

Repeat until the run reaches `completed` or `failed`.

### Step 6: Present final result

```
## Autopilot Complete

**Run:** {run_id}
**Status:** {status}
**Stages:**
{for each stage: emoji name — status}

{If completed: "Pipeline finished successfully."}
{If failed: "Pipeline failed at {current_stage}: {failure_reason}"}
```

## Rules

- Always show the spec before starting — let the user confirm
- Never skip the prepare step — it validates the spec and classifies tier
- If the pipeline fails, explain why clearly — don't just show raw error
- For paused runs, always show what's blocking before asking to resume
- The pipeline runs locally — state is persisted to `~/.agentcouncil/autopilot/`

## Current Limitations

- `plan` and `build` stages use stub runners — they produce minimal artifacts
- Gates use stub protocol artifacts, not live backend deliberation sessions
- `spec_prep`, `verify`, and `ship` have real runners with actual execution
