---
name: review
description: Run the AgentCouncil review protocol. You (Claude) frame the review question and direct the outside agent to the right files. The outside agent reviews independently. Use when work is done and you want independent critique.
allowed-tools: mcp__agentcouncil__outside_start mcp__agentcouncil__outside_reply mcp__agentcouncil__outside_close mcp__agentcouncil__get_outside_backend_info
argument-hint: [what to review — plan, implementation, milestone, design]
---

# AgentCouncil Review

You are running the AgentCouncil review protocol. You are the orchestrator — the one who built or owns the thing being reviewed. The outside agent is the independent reviewer with fresh eyes.

**Target:** $ARGUMENTS

## Backend Selection

Parse the arguments for `backend=<value>` (e.g., `backend=codex`, `backend=claude`, `backend=ollama`). If omitted, the default backend is used. The `backend` argument selects which provider to use. Provider differences are handled automatically by the session layer.

## Protocol — follow these steps exactly

### Step 0: Get backend capabilities

Call `mcp__agentcouncil__get_outside_backend_info` with `profile` set to the parsed backend value. If no `backend=` was specified, omit the `profile` argument.

Save `workspace_access` from the response. This determines how to construct the review request:
- If `workspace_access` is `"native"`: include file paths in the prompt — the outside agent can read them directly.
- If `workspace_access` is `"assisted"` or `"none"`: read the relevant files yourself and include their contents in the prompt — the outside agent cannot access the workspace.

### Step 1: Gather context and frame the review

Read the relevant files yourself. Determine:
- What is being reviewed? (plan, implementation, milestone, design, code)
- What specifically should the reviewer look at? (file paths)
- What question should the reviewer answer?
- What concerns or focus areas matter?

Display what you're sending for review so the user can see the framing.

### Step 2: Send directed review request to outside agent

Construct a review request that tells the reviewer:
- What to review (be specific — name files, requirements, decisions)
- Where to look (file paths the reviewer should read)
- What question to answer (completeness? feasibility? security? correctness?)
- Focus areas and key concerns

If `workspace_access` is `"native"`: include file paths in the prompt — the outside agent can read them directly. Do NOT dump file contents.

If `workspace_access` is `"assisted"` or `"none"`: read the relevant files yourself and include their contents in the prompt — the outside agent cannot access the workspace.

Call `mcp__agentcouncil__outside_start` with `prompt` set to the review request and `profile` set to the backend argument (or omit `profile` for default). Save `session_id` from the response.

### Step 3: Read findings and respond with context

The reviewer returns findings with severity, impact, evidence, and confidence.

Read each finding and respond with your knowledge of the codebase and intent:
- **Confirm** findings that are valid: "Good catch — that's a real gap"
- **Dispute** findings with evidence: "That's handled in adapters.py:157, see the validation check"
- **Add context** the reviewer couldn't know: "We intentionally skipped that because..."

Send your response via `mcp__agentcouncil__outside_reply` with the saved `session_id`. Ask for a final synthesis. The session layer handles history management — just send the new message.

The synthesis request: "Based on my responses to your findings, produce a final synthesis. Return JSON with these exact keys: verdict (pass/revise/escalate), summary (string), findings (array of objects with id, title, severity, impact, description, evidence, locations, confidence, agreement, origin, source_refs), strengths (array of strings), open_questions (array of strings), next_action (string). Mark agreement as confirmed if I agreed, disputed if I provided counter-evidence. Verdict: pass if no confirmed critical/high findings, revise if any confirmed high+, escalate if confirmed critical with high confidence."

### Step 3.5: Close session

Call `mcp__agentcouncil__outside_close` with the saved `session_id`.

### Step 4: Present the structured result

Parse the JSON response and present:

```
## Review Result

**Verdict:** {verdict}

### Summary
{summary}

### Findings
For each finding:
- **[{id}] {title}** (severity: {severity}, confidence: {confidence})
  Impact: {impact}
  Agreement: {agreement} | Origin: {origin}

### Strengths
- {each strength}

### Open Questions
- {each question}

### Next Action
{next_action}
```

If JSON fails to parse, report verdict as "escalate" and show raw response.

## Rules

- You are NOT a second reviewer — you are the builder responding to critique
- Do NOT write your own review before sending to the outside agent
- Frame the review question precisely — vague requests get vague reviews
- When workspace_access is native: point the reviewer to specific files, not raw content dumps
- Findings describe IMPACT, not fixes
- Disputed findings are preserved, not collapsed
- Always call `outside_close` after the final synthesis response
- The session layer handles history management — just send the new message each turn
- Adapt file inclusion to workspace_access: paths for native, inline contents for assisted/none
