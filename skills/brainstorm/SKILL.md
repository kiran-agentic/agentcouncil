---
name: brainstorm
description: Run the AgentCouncil deliberation protocol. You (Claude) act as orchestrator AND lead agent. An independent outside agent provides a second perspective via the AgentCouncil session API. Use when you want genuinely independent perspectives before converging on a decision.
allowed-tools: mcp__agentcouncil__outside_start mcp__agentcouncil__outside_read mcp__agentcouncil__outside_reply mcp__agentcouncil__outside_close mcp__agentcouncil__get_outside_backend_info
argument-hint: [topic or question to brainstorm]
---

# AgentCouncil Brainstorm

You are running the AgentCouncil deliberation protocol. You are BOTH the orchestrator and the lead agent. The outside agent runs independently.

**Topic:** $ARGUMENTS

## Backend Selection

Parse the arguments for `backend=<value>` (e.g., `backend=codex`, `backend=claude`, `backend=ollama`). If omitted, the default backend is used. The `backend` argument selects which provider to use. Provider differences (session persistence, workspace access) are handled automatically by the session layer.

## Protocol — follow these steps exactly

### Step 0: Get backend capabilities

Call `mcp__agentcouncil__get_outside_backend_info` with `profile` set to the parsed backend value. If no `backend=` was specified, omit the `profile` argument.

Save `workspace_access` from the response. This determines how to construct prompts:
- If `workspace_access` is `"native"`: reference file paths in prompts — the outside agent can read them directly.
- If `workspace_access` is `"assisted"` or `"none"`: read relevant files yourself and inline their contents in prompts — the outside agent cannot access the workspace.

### Step 1: State the problem

Clearly state what needs to be decided and why it matters. This frames the deliberation for both agents and the user.

### Step 2: Create the brief and send to outside agent FIRST

Write a neutral brief containing ONLY:
- Problem statement
- Background context
- Constraints
- Goals
- Open questions

**CRITICAL:** Do NOT include any proposal, opinion, or direction. The brief must be clean.

For prompt construction:
- If `workspace_access` is `"native"`: include file paths in the brief for the outside agent to read. Add this hint at the end of the brief: "If you have access to code navigation tools (e.g. serena, codegraph), use them to understand the codebase structure before forming your proposal."
- If `workspace_access` is `"assisted"` or `"none"`: read the relevant files yourself and include their contents in the brief.

Call `mcp__agentcouncil__outside_start` with `prompt` set to the brief text, `profile` set to the backend argument (or omit `profile` for default), and `await_response` set to `false`. This fires the brief to the outside agent and returns immediately with `session_id` and `status: "pending"`. The outside agent is now working on its proposal in the background.

### Step 3: Write YOUR proposal (parallel with outside agent)

The outside agent is processing the brief in the background. Write your own independent proposal NOW — do not wait. You have the full conversation context — use it. Be specific and opinionated.

Display it clearly labeled as **Claude's proposal**.

**Independence is preserved** because the brief was neutral (no opinion) and you have not read the outside agent's response yet. Both agents think independently.

### Step 4: Read outside agent's proposal and share yours

Call `mcp__agentcouncil__outside_read` with the saved `session_id` to fetch the outside agent's response (this blocks until ready, but the agent has been working since Step 2).

Display it clearly labeled as **Outside agent's proposal**.

Then send your full proposal so the outside agent can compare both views.

Call `mcp__agentcouncil__outside_reply` with the saved `session_id` and this prompt:

"Here is the lead agent's independent proposal (written before seeing yours): {your full proposal from Step 3}. Compare it with your own proposal. Where do you agree? Where do you disagree? Push back where you think the lead is wrong."

### Step 5: Compare proposals

Now both agents have seen each other's work. Display the outside agent's comparison response. Summarize where the two proposals agree and disagree.

### Step 6: Exchange rounds (with early exit)

Default to 1 round unless the user asks for more. For each exchange after Step 5:

**Read the outside agent's response.** If there are no material disagreements — both proposals align on direction, details, and tradeoffs — skip remaining exchanges and go directly to Step 7 (synthesis). State: "No material disagreements — proceeding to synthesis."

**If disagreements exist:** Write your counter-response addressing their pushback.

Call `mcp__agentcouncil__outside_reply` with the saved `session_id` and the new prompt. The session layer handles history management — just send the new message each turn.

### Step 7: Get synthesis

Call `mcp__agentcouncil__outside_reply` with the saved `session_id` and this prompt:

"Based on our full discussion, produce a final synthesis. Return JSON with these exact keys: recommended_direction (string), agreement_points (list of strings), disagreement_points (list of strings), rejected_alternatives (list of strings), open_risks (list of strings), next_action (string), status (one of: consensus, consensus_with_reservations, unresolved_disagreement). Do NOT use partial_failure as status."

### Step 8: Present the result

Parse the JSON response and present:

```
## Brainstorm Result

**Status:** {status}

### Recommended Direction
{recommended_direction}

### Agreement Points
- {each point}

### Disagreement Points
- {each point}

### Rejected Alternatives
- {each point}

### Open Risks
- {each risk}

### Next Action
{next_action}
```

If JSON fails to parse, report status as "unresolved_disagreement" and show raw response.

### Step 8.5: Close session

Call `mcp__agentcouncil__outside_close` with the saved `session_id`.

## Rules

- Default to 1 round unless the user asks for more
- ALWAYS send the brief FIRST so the outside agent starts immediately
- Write your proposal AFTER sending the brief but BEFORE reading the response
- NEVER put your opinion in the brief
- Always call `outside_close` after the final synthesis response
- The session layer handles history management — just send the new message each turn
- Adapt prompt construction to workspace_access: file paths for native, inline contents for assisted/none
- Do NOT add analysis beyond the structured result
