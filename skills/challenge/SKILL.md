---
name: challenge
description: Run the AgentCouncil challenge protocol. You (Claude) send the plan and defend it. An independent outside agent attacks assumptions and finds failure modes via the AgentCouncil session API. Use when you want adversarial stress-testing before shipping.
allowed-tools: mcp__agentcouncil__outside_start mcp__agentcouncil__outside_reply mcp__agentcouncil__outside_close mcp__agentcouncil__get_outside_backend_info
argument-hint: [plan or design to stress-test]
---

# AgentCouncil Challenge

You are running the AgentCouncil challenge protocol. You are the orchestrator and defender — you built or own the plan being tested. The outside agent is the independent attacker trying to break it.

**Target:** $ARGUMENTS

## Backend Selection

Parse the arguments for `backend=<value>` (e.g., `backend=codex`, `backend=claude`, `backend=ollama`). If omitted, the default backend is used. Provider differences (session persistence, workspace access) are handled automatically by the session layer.

## Protocol — follow these steps exactly

### Step 0: Get backend capabilities

Call `mcp__agentcouncil__get_outside_backend_info` with `profile` set to the parsed backend argument (or omit `profile` if no `backend=` argument was given).

Save `workspace_access` from the response.

### Step 1: Identify the target

Read the relevant files. Determine:
- What plan/design/approach is being challenged?
- What are the key assumptions?
- What does success look like?
- What are the constraints?

Display the target and assumptions so the user can see what's being stress-tested.

### Step 2: Send attack brief to outside agent

Construct an attack request that gives the attacker:
- The target artifact (plan, design, or approach)
- Assumptions to attack (be explicit)
- Success criteria
- Constraints
- Explicit instruction: find failure modes, attack assumptions, do NOT propose fixes

For file context:
- If `workspace_access` is `native`: include file paths for the attacker to read implementation details directly. Add this hint at the end of the attack brief: "If you have access to code navigation tools (e.g. serena, codegraph), use them to trace call chains, dependencies, and edge cases before attacking."
- If `workspace_access` is `assisted` or `none`: read the relevant files yourself and include implementation details in the prompt.

Call `mcp__agentcouncil__outside_start` with `prompt` set to the attack brief and `profile` set to the backend argument (or omit `profile` for default). Save `session_id` from the response. Save `response` as the attacker's first reply.

### Step 3: Read attacks and DEFEND

The attacker returns failure modes with severity, impact, and confidence.

Read each attack and defend the plan with your codebase knowledge:
- **Rebut** attacks that are wrong: "Redis failover is handled by Sentinel, see infra/redis.yaml"
- **Concede** attacks that land: "Good catch — the batch import endpoint bypasses the cache layer entirely"
- **Add evidence** either way: "The latency assumption is backed by 30 days of production metrics"

Send your defense via `mcp__agentcouncil__outside_reply` with the saved `session_id`.

### Step 4: Attacker attacks the defense (exchange round)

Default to 1 exchange round (2 total rounds including initial). The attacker responds to your defense specifically — attacking your rebuttals, not the original artifact.

Read the counter-attack from the response. Send your counter-defense via `mcp__agentcouncil__outside_reply` with the saved `session_id`.

For additional rounds requested by the user, repeat this step.

### Step 5: Get synthesis

Send the synthesis request via `mcp__agentcouncil__outside_reply` with the saved `session_id`:

"Based on our full attack/defense discussion, produce a final synthesis. Return JSON with these exact keys: readiness (ready/needs_hardening/not_ready), summary (string), failure_modes (array of objects with id, assumption_ref, description, severity, impact, confidence, disposition, mitigation, source_refs), surviving_assumptions (array of strings), break_conditions (array of strings), residual_risks (array of strings), next_action (string). Rules: adversarial only — do NOT propose repairs or fixes. Set readiness to ready ONLY if no credible attack survived my defense. Set disposition to must_harden/monitor/mitigated/accepted_risk/invalidated based on whether my defense held."

### Step 5.5: Close session

Call `mcp__agentcouncil__outside_close` with the saved `session_id`.

### Step 6: Present the structured result

Parse the JSON response from Step 5 and present:

```
## Challenge Result

**Readiness:** {readiness}

### Summary
{summary}

### Failure Modes
For each failure mode:
- **[{id}] {assumption_ref}** (severity: {severity}, disposition: {disposition})
  Description: {description}
  Impact: {impact}
  Confidence: {confidence}

### Surviving Assumptions
- {each assumption that withstood attack}

### Break Conditions
- {each condition under which the plan fails}

### Residual Risks
- {each remaining risk}

### Next Action
{next_action}
```

If JSON fails to parse, report readiness as "not_ready" and show raw response.

## Rules

- You are the DEFENDER — respond to attacks with evidence, not agreement
- Default to 2 rounds (1 exchange round after initial attack/defense)
- Frame the attack brief precisely — list specific assumptions to attack
- Adversarial only: attacker finds failure modes, does NOT propose repairs
- Exchange rounds attack your DEFENSE arguments, not the original artifact
- Always call `outside_close` after the final synthesis response
- The session layer handles history management — just send the new message each turn
- Adapt file inclusion to workspace_access: file paths for native, inline contents for assisted/none
