---
name: decide
description: Run the AgentCouncil decide protocol. You (Claude) define the decision space and options. An independent outside agent evaluates via the AgentCouncil session API. Use when you have multiple options and need to pick one.
allowed-tools: mcp__agentcouncil__outside_start mcp__agentcouncil__outside_reply mcp__agentcouncil__outside_close mcp__agentcouncil__get_outside_backend_info
argument-hint: [decision question]
---

# AgentCouncil Decide

You are running the AgentCouncil decide protocol. You are the orchestrator — you define the decision space and provide context. The outside agent is the independent evaluator.

**Decision:** $ARGUMENTS

## Backend Selection

Parse the arguments for `backend=<value>` (e.g., `backend=codex`, `backend=claude`, `backend=ollama`). If omitted, the default backend is used. Provider differences (session persistence, workspace access) are handled automatically by the session layer.

## Protocol — follow these steps exactly

### Step 0: Get backend capabilities

Call `mcp__agentcouncil__get_outside_backend_info` with `profile` set to the parsed backend argument (or omit `profile` if no `backend=` argument was given).

Save `workspace_access` from the response.

### Step 1: Identify the decision and define options

From the conversation context and codebase, determine:
- The decision question
- The options (minimum 2, each with id, label, description)
- Evaluation criteria (what matters?)
- Constraints (what limits the choice?)

Display the decision space so the user can see exactly what's being evaluated.

### Step 2: Send decision request to outside agent

Construct an evaluation request that gives the evaluator:
- The decision question
- Each option with clear descriptions
- Criteria and constraints
- Explicit instruction: evaluate ONLY these options, do NOT invent new ones

For file context:
- If `workspace_access` is `native`: include file paths for the evaluator to read directly. Do NOT dump file contents. Add this hint at the end of the evaluation request: "If you have access to code navigation tools (e.g. serena, codegraph), use them to understand the codebase before evaluating options."
- If `workspace_access` is `assisted` or `none`: read the relevant files yourself and include key content in the prompt.

Call `mcp__agentcouncil__outside_start` with `prompt` set to the evaluation request and `profile` set to the backend argument (or omit `profile` for default). Save `session_id` from the response. Save `response` as the evaluator's first reply.

### Step 3: Read assessments and respond with context

The evaluator returns: for each option, pros, cons, blocking risks, disposition, confidence.

Read the assessments and respond with your codebase knowledge:
- Correct factual errors: "Option B's 'extra infra' con is overstated — we already run Redis"
- Add context: "Option A integrates with our existing auth middleware, see auth.py"
- Challenge assumptions: "The latency claim for Option C assumes us-east — we're in eu-west"

Send your response with context corrections via `mcp__agentcouncil__outside_reply` with the saved `session_id`. Include the synthesis request prompt:

"Based on my context corrections, produce a final decision synthesis. Return JSON with these exact keys: outcome (decided/deferred/experiment), winner_option_id (string or null), decision_summary (string), option_assessments (array of objects with option_id, pros, cons, blocking_risks, disposition, confidence, source_refs), defer_reason (string or null), experiment_plan (string or null), revisit_triggers (array of strings), next_action (string). Rules: evaluate ONLY the provided options. For EVERY option include assumptions, tradeoffs, and confidence. Set disposition to selected/viable/rejected/insufficient_information. Outcome: decided if one option clearly superior, deferred if insufficient info, experiment if needs real-world validation."

### Step 3.5: Close session

Call `mcp__agentcouncil__outside_close` with the saved `session_id`.

### Step 4: Present the structured result

Parse the JSON response from Step 3 and present:

```
## Decision Result

**Outcome:** {outcome}
**Winner:** {winner_option_id or "None"}

### Decision Summary
{decision_summary}

### Option Assessments
For each option:
- **{option_id}: {label}** (disposition: {disposition}, confidence: {confidence})
  Pros: {pros}
  Cons: {cons}
  Blocking Risks: {blocking_risks or "None"}

### Revisit Triggers
- {each trigger}

### Next Action
{next_action}
```

If JSON fails to parse, report outcome as "deferred" and show raw response.

## Rules

- You define the decision space — the evaluator works within it
- Do NOT write your own assessment before sending to the outside agent
- The evaluator can ONLY evaluate provided options — it cannot invent new ones
- Always call `outside_close` after the final synthesis response
- The session layer handles history management — just send the new message each turn
- Adapt file inclusion to workspace_access: file paths for native, inline contents for assisted/none
