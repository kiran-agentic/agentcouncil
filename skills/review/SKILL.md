---
name: review
description: Run the AgentCouncil review protocol. You (Claude) frame the review question and direct the outside agent to the right files. The outside agent reviews independently. Use when work is done and you want independent critique. Supports --loop for iterative convergence (fix → re-review → verify until clean).
allowed-tools: mcp__agentcouncil__outside_start mcp__agentcouncil__outside_reply mcp__agentcouncil__outside_close mcp__agentcouncil__get_outside_backend_info
argument-hint: [what to review — plan, implementation, milestone, design] [--loop to iterate until clean]
---

# AgentCouncil Review

You are running the AgentCouncil review protocol. You are the orchestrator — the one who built or owns the thing being reviewed. The outside agent is the independent reviewer with fresh eyes.

**Target:** $ARGUMENTS

## Mode Detection

Parse the arguments for convergence mode. Use **iterative convergence** if ANY of these are true:
- The user included `--loop`, `--converge`, or `--iterate` in arguments
- The user's request explicitly asks for iterative behavior: "fix until clean", "keep reviewing", "iterate until no findings", "review and fix", "repeat until pass"

Otherwise, use **one-shot review** (Steps 0–5 below).

If convergence mode is detected, follow Steps 0–2 for the first pass, then switch to the **Convergence Loop** protocol (at the bottom of this file) instead of Steps 3–5.

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

If `workspace_access` is `"native"`: include file paths in the prompt — the outside agent can read them directly. Do NOT dump file contents. Add this hint at the end of the review request: "If you have access to code navigation tools (e.g. serena, codegraph), use them to trace dependencies, callers, and related code before reviewing."

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

### Step 5: Convergence hint (conditional)

If the verdict is `revise` or `escalate` and there are confirmed findings, add this hint after the result:

> To iterate on these findings until clean, run `/review --loop`

Do NOT show this hint if:
- The verdict is `pass`
- There are no confirmed findings
- The user already used `--loop` mode

## Convergence Loop (used when `--loop` is detected)

You orchestrate the loop in this session. YOU are the lead — you edit the files between iterations using Read/Edit/Grep. The outside agent is the verifier: each iteration it re-reads the current state of the artifact and updates finding statuses.

### Loop parameters

- `max_iterations`: default `3`, hard cap `10`. Parse from arguments if the user passed `iterations=N`; otherwise use `3`.
- One **iteration** = (outside assesses current state) → (you apply edits). Clarifying back-and-forth with the outside agent WITHIN an iteration is not counted — only the full fix-cycles are bounded.
- A finding's status is one of: `open` (still present), `fixed` (reviewer confirms resolved this iteration), `verified` (fixed in a prior iteration and still gone), `reopened` (was fixed, now present again), `wont_fix` (you marked it intentional).

### Loop protocol

**Iteration 1 (first pass):**
1. Do Step 0 (backend capabilities) and Step 1 (gather context, frame the question) as in one-shot mode.
2. Do Step 2 but append this clause to the review request:
   > Return findings as JSON with these exact keys: `findings` (array of `{id, title, severity, impact, description, evidence, locations, confidence}`), `summary` (string), `verdict` (pass/revise/escalate). Use stable IDs (F1, F2, ...) — I'll reference them in follow-up.
3. Call `outside_start` and save `session_id`. Parse the JSON findings.
4. Display the findings to the user, grouped by severity. Ask no questions — present the list.
5. Go to **Edit and verify** below.

**Edit and verify (runs at the end of each iteration except the last):**
1. For each finding you agree with: apply the fix using your own tools (Read, Edit, Grep, Bash). For findings you dispute, mark them `wont_fix` internally with a one-line rationale.
2. **Intra-iteration dialogue (optional, unbounded):** if a finding is ambiguous — wrong file, unclear location, disputed evidence — call `outside_reply` with a clarifying question first. These exchanges don't count toward `max_iterations`. Examples: "F3 cites lines 84–98 but that range is empty — did you mean a different section?" or "F5 says 'conflated invariants' — which invariant specifically?" Resolve ambiguity before editing.
3. Summarize what you changed, in one paragraph per finding. Keep it concrete: file paths and what actually changed, not intent.
4. If you've hit `max_iterations`, skip straight to the close step below.
5. Otherwise increment the iteration counter and go to **Verification pass**.

**Verification pass (iteration 2+):**
1. Call `outside_reply` with this prompt:
   > I've applied fixes to the artifact. Re-read the files (paths unchanged) and return JSON with: `finding_updates` (array of `{id, status, reviewer_notes}` for EVERY prior finding, where status ∈ `fixed|open|reopened`), `new_findings` (array of any NEW issues introduced by the changes, same schema as iteration 1), `verdict` (pass/revise/escalate). My change summary: <paste your change summary here>.
2. Parse the response. Merge:
   - `status=fixed` in iteration 2 → if it remains absent in iteration 3, promote to `verified`. Otherwise still `fixed`.
   - `status=open` → remains `open`.
   - `status=reopened` → was previously `fixed`/`verified`, now `open` again.
   - `new_findings` → add with new stable IDs (F{n+1}, F{n+2}, ...).
3. Update the running ConvergenceResult you'll present at the end.
4. **Exit conditions** (check after each verification pass, in this order):
   - All findings are `verified` or `wont_fix` → exit with verdict `pass`.
   - Iteration counter == `max_iterations` → exit with the latest verdict from outside.
   - Otherwise: loop back to **Edit and verify**.

**Close step (always runs once on exit):**
1. Call `outside_close` with the `session_id`.
2. Present the final **ConvergenceResult**:

```
## Convergence Result

**Verdict:** {final_verdict}
**Iterations:** {n} of {max_iterations}
**Exit reason:** {all_verified | max_iterations_reached | escalated}

### Final findings
For each finding:
- **[{id}] {title}** — status: {status} (severity: {severity})
  {impact}
  {if status=wont_fix: Rationale: {your rationale}}

### Changes applied across iterations
- Iteration 1: {change summary}
- Iteration 2: {change summary}
- ...

### Open or reopened findings
{list, or "None — all findings verified or intentionally skipped"}
```

### Loop rules

- You do the file edits — not the server, not a subprocess. Your native Read/Edit/Grep access is the whole point.
- Intra-iteration dialogue is free; fix-cycles are bounded by `max_iterations`.
- If the outside agent returns non-JSON or malformed JSON at any iteration, retry the same prompt once with "return ONLY valid JSON, no prose wrapper." If the second attempt also fails, close the session and report verdict `escalate` with the raw response.
- If you apply zero edits in an iteration (e.g., all remaining findings are `wont_fix`), skip the next verification pass and exit directly.
- Always `outside_close` on exit — even on error paths.

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
