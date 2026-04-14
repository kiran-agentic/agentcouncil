---
name: inspect
description: Inspect past AgentCouncil deliberation sessions. View transcripts, findings, provenance, and protocol history from the journal. Use when you want to look back at a past brainstorm, review, decide, or challenge session.
allowed-tools: mcp__agentcouncil__journal_list mcp__agentcouncil__journal_get mcp__agentcouncil__journal_stream
argument-hint: [session_id or "recent" to list recent sessions]
---

# AgentCouncil Inspect

View past deliberation sessions from the journal.

**Target:** $ARGUMENTS

## Protocol — follow these steps

### Step 1: Determine what to show

Parse the arguments:
- If the user provides a **session_id** (UUID-like string): retrieve that specific session
- If the user says **"recent"**, **"list"**, or provides no arguments: list recent sessions
- If the user asks about a specific protocol type: filter by type

### Step 2: List recent sessions (if no specific session)

Call `mcp__agentcouncil__journal_list` with optional `protocol` filter.

Present the results as a table:

```
| Session ID | Protocol | Status | Started |
|------------|----------|--------|---------|
| abc-123... | review   | consensus | 2026-04-14 12:00 |
```

If the user wants details on a specific session, proceed to Step 3.

### Step 3: Show session details

Call `mcp__agentcouncil__journal_get` with the `session_id`.

Present the session in a readable format:
- **Protocol type** and **status**
- **Timestamps** (started, ended)
- **Transcript**: Show who said what, in order
  - Mark proposals with [PROPOSAL], exchanges with [EXCHANGE]
  - Show actor provider/model if available
  - For specialist evidence, show the sub-question and assessment
- **Artifact**: Show the structured result (verdict/direction/readiness)
- **Finding status** (for convergence loop sessions): show progression (open → fixed → verified)

### Step 4: Stream events (if requested)

If the user asks to see events or stream:

Call `mcp__agentcouncil__journal_stream` with `session_id` and optional `since_cursor`.

Show events chronologically with type and data.

## Rules

- This is read-only inspection — never modify journal entries
- Show the most relevant information first (artifact/verdict, then transcript details)
- For long transcripts, summarize rather than dumping everything
- If the session is not found, suggest listing recent sessions
