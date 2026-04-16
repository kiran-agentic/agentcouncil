# SPEC: AgentCouncil v2.0 — Deliberation Infrastructure

*Spec for 8 roadmap items covering durability, iterative workflows, multi-agent expansion, and observability.*

## 1. Objective

### What we're building

The deliberation infrastructure layer beneath AgentCouncil's four protocols (brainstorm, review, decide, challenge). This adds:

- **Durability** — Persistent session transcripts with turn-level provenance
- **Iterative workflows** — Review findings that loop until verified, not fire-and-forget
- **Multi-agent expansion** — Bounded specialist consultation and sealed N-party proposals
- **Observability** — Cursor-based event streaming and a CLI session viewer

### Target users

- Developers using AgentCouncil inside Claude Code who want deliberation results that persist, resume, and iterate
- Automation consumers polling for deliberation completion
- Teams auditing past agent decisions

### What this is NOT

- Not the full v2.0 vision (Decompose, Execute, Autopilot, Federate are out of scope)
- Not a chat room, meeting room, or free-form multi-agent discussion system
- Not a desktop application or interactive UI

### Core principle (unchanged)

**Independence before convergence.** Every component must strengthen or extend this principle.

---

## 2. Components

### 2.1 Deliberation Journal

**Module:** `agentcouncil/journal.py`

Persists session metadata, transcript turns, and final artifacts to `~/.agentcouncil/journal/`.

**Commands / API surface:**

| MCP Tool | Purpose |
|----------|---------|
| `journal_list(limit?, protocol?)` | List recent journal entries with metadata |
| `journal_get(session_id)` | Retrieve a full journal entry |

**Acceptance criteria:**

- [DJ-01] Every completed protocol run (brainstorm, review, decide, challenge) persists a journal entry automatically
- [DJ-02] Journal entry contains: session_id, protocol_type, start_time, end_time, status, artifact, and ordered transcript turns
- [DJ-03] Each transcript turn carries provenance fields: `actor_id`, `actor_provider`, `actor_model`, `phase`, `timestamp`, `parent_turn_id`
- [DJ-04] Schema version field is present in every entry (initial: `"1.0"`)
- [DJ-05] Writes are atomic: temp file + rename. No partial writes on crash
- [DJ-06] Journal entries stored as one JSON file per session: `~/.agentcouncil/journal/{session_id}.json`
- [DJ-07] `journal_list` returns entries sorted by start_time descending, with optional protocol filter
- [DJ-08] `journal_get` returns full entry or raises ValueError for unknown session_id
- [DJ-09] Provider credentials and API keys are NEVER persisted in journal entries
- [DJ-10] Journal directory is created lazily on first write, not at import time
- [DJ-11] Existing v1.x protocol behavior is unchanged — journaling is a side effect, not a protocol change

### 2.2 Transcript Normalization

**Files modified:** `agentcouncil/schemas.py`, `agentcouncil/deliberation.py`

Unifies the two incompatible transcript shapes into a single model all protocols use.

**Current state (the problem):**
- Generic protocols (review, decide, challenge) use `Transcript` with `TranscriptTurn` containing `role`, `content`, `source_refs`
- Brainstorm uses `RoundTranscript` with `brief_prompt`, `outside_proposal`, `lead_proposal`, `exchanges[]`, `negotiation_output` as separate top-level fields
- The `Exchange` model in brainstorm has `role` + `content` but is a different type from `TranscriptTurn`
- `TranscriptMeta` stores provenance at the envelope level (lead_backend, outside_backend, etc.) — not per turn

**Target state:**
- A single `NormalizedTranscript` model (or unified `Transcript`) where every contribution is a `TranscriptTurn`
- Brainstorm's `outside_proposal` becomes a turn with `phase="proposal"`, `role="outside"`
- Brainstorm's `lead_proposal` becomes a turn with `phase="proposal"`, `role="lead"`
- Exchange rounds become turns with `phase="exchange"`, numbered
- Synthesis becomes a turn with `phase="synthesis"`
- Per-turn provenance replaces envelope-level `TranscriptMeta`

**Functionality guarantee:** Zero user-visible behavior changes. All four protocol flows (brief -> propose -> exchange -> synthesize) remain identical. All artifact output shapes (`ConsensusArtifact`, `ReviewArtifact`, `DecideArtifact`, `ChallengeArtifact`) remain identical. Prompt construction and synthesis logic remain identical. Skill consumers never access transcript internals directly — only artifacts.

**Acceptance criteria:**

- [TN-01] All four protocols produce transcripts using the same `Transcript` model with `TranscriptTurn` entries
- [TN-02] `TranscriptTurn` gains provenance fields: `actor_id`, `actor_provider`, `actor_model`, `phase`, `timestamp`, `parent_turn_id` (all Optional for backward compat)
- [TN-03] `phase` is an enum or literal: `"brief"`, `"proposal"`, `"exchange"`, `"synthesis"`, `"specialist"`, `"convergence"`
- [TN-04] `RoundTranscript` is deprecated with a migration path — existing code that constructs `BrainstormResult` is updated
- [TN-05] `BrainstormResult.transcript` type changes from `RoundTranscript` to `Transcript`
- [TN-06] Existing artifact output shapes (`ConsensusArtifact`, `ReviewArtifact`, `DecideArtifact`, `ChallengeArtifact`) are NOT changed — only internal transcript representation changes
- [TN-07] `TranscriptMeta` remains available on the `Transcript` model for backward compatibility but is marked deprecated
- [TN-08] All existing tests pass after normalization (updated to use new transcript shape)

### 2.3 Resumable Protocol State Model

**Module:** `agentcouncil/workflow.py`

A protocol state machine that can checkpoint at phase boundaries and resume from the last checkpoint.

**Acceptance criteria:**

- [RP-01] Protocol runs can be checkpointed at defined phase boundaries
- [RP-02] Phase boundaries: after brief sent, after proposals received, after each exchange round, after specialist evidence, after each convergence iteration, before synthesis
- [RP-03] Checkpoints are persisted via the Deliberation Journal — stored as `state` field in journal entry
- [RP-04] New MCP tool `protocol_resume(session_id)` reconstructs protocol state from the last checkpoint and continues execution
- [RP-05] `protocol_resume` raises ValueError if session_id is unknown or protocol already completed
- [RP-06] Initial implementation: review protocol only. Other protocols added later
- [RP-07] Checkpoint contains: protocol_type, current_phase, accumulated_turns, pending_input, provider config needed to reconstruct session
- [RP-08] No arbitrary mid-turn checkpointing — only at phase boundaries
- [RP-09] Resumed protocols produce the same artifact type as non-resumed runs — no special "resumed" artifact shape

### 2.4 Turn Stream

**Module:** Extension to `agentcouncil/journal.py`

Append-only event log with cursor-based retrieval for observability and incremental inspection.

**Acceptance criteria:**

- [TS-01] Each journal entry contains an ordered `events` list alongside the transcript
- [TS-02] Events include: `turn_added`, `phase_transition`, `status_change`, `specialist_evidence`, `finding_status_change`
- [TS-03] Each event has: `event_id` (monotonic integer), `event_type`, `timestamp`, `data` (type-specific payload)
- [TS-04] New MCP tool `journal_stream(session_id, since_cursor?)` returns events since cursor with `next_cursor`
- [TS-05] When `since_cursor` is omitted, returns all events from the beginning
- [TS-06] Retrieval is read-only and side-effect-free
- [TS-07] Cursors are monotonic integers (event_id), not opaque tokens — simple and predictable
- [TS-08] `journal_stream` on unknown session_id raises ValueError
- [TS-09] Events are appended during protocol execution, not reconstructed after the fact

### 2.5 Convergence Loops (Review Only)

**Module:** `agentcouncil/convergence.py`

Iterative review workflow: findings -> fix -> scoped re-review -> verify resolution -> loop or approve.

**Acceptance criteria:**

- [CL-01] New MCP tool `review_loop(artifact, artifact_type, review_objective?, focus_areas?, max_iterations?, profile?, model?)` runs the convergence loop
- [CL-02] Default `max_iterations` is 3, configurable per call
- [CL-03] Each iteration produces findings with per-finding status: `open`, `fixed`, `verified`, `reopened`, `wont_fix`
- [CL-04] Between iterations, the lead produces an `AddressedChange` artifact describing what was fixed for each finding
- [CL-05] Re-review is scoped: outside agent receives prior findings + change summary, NOT a full re-review prompt
- [CL-06] Loop exits when: (a) all findings reach `verified` or `wont_fix`, (b) max_iterations reached, or (c) outside agent signals explicit approval
- [CL-07] The "approved" signal is a typed field in the re-review response, not a conversational statement
- [CL-08] Final artifact: `ConvergenceResult` containing iteration history, final finding statuses, total iterations, exit_reason
- [CL-09] Each finding has a stable identity across iterations — findings are identified by `id` assigned in the first iteration, tracked through subsequent iterations
- [CL-10] `wont_fix` findings include the lead's rationale, which the outside agent sees in re-review
- [CL-11] The lead cannot skip re-review — if open findings exist, convergence requires verification
- [CL-12] Hard cap on iterations enforced — no infinite loops regardless of configuration
- [CL-13] Convergence Loop state is persisted via Deliberation Journal and resumable via protocol state model
- [CL-14] Existing one-shot `review` tool continues to work unchanged — convergence is a separate tool

**Finding identity design: Caller-assigned IDs with system fallback.**

Uses the existing `Finding.id` field (`schemas.py:128`) — the outside agent already assigns IDs (e.g., `R-01`, `R-02`) in every review today.

**How it works across iterations:**

```
Iteration 1:
  Outside agent produces:
    Finding(id="R-01", title="Missing input validation", severity="high")
    Finding(id="R-02", title="SQL injection risk", severity="critical")

  Lead addresses R-01 and R-02, produces AddressedChange for each

Iteration 2 (scoped re-review):
  Outside agent receives prior findings with their IDs in the re-review prompt
  Outside agent responds referencing the same IDs:
    R-01: verified (fix looks correct)
    R-02: reopened (parameterized queries not used everywhere)
    R-03: NEW finding (regression introduced by the fix)
```

**System enforcement (not left to the agent):**
- [CL-15] IDs are validated unique within each iteration (reject duplicates)
- [CL-16] Prior iteration IDs are provided to the agent in the re-review prompt — agent doesn't need to remember
- [CL-17] If an ID from iteration N isn't mentioned in iteration N+1, its status carries forward unchanged (not silently dropped)
- [CL-18] If the agent omits an ID field, system generates fallback: `f"{severity[0].upper()}-{sha256(title)[:6]}"`
- [CL-19] ID format is validated on parse — must be non-empty string, max 20 characters

**Loop artifact schema:**

```python
class FindingIteration(BaseModel):
    finding_id: str
    status: Literal["open", "fixed", "verified", "reopened", "wont_fix"]
    addressed_change: Optional[str] = None  # lead's description of fix
    wont_fix_rationale: Optional[str] = None
    reviewer_notes: Optional[str] = None  # outside agent's verification notes

class ConvergenceIteration(BaseModel):
    iteration: int
    findings: list[FindingIteration]
    approved: bool = False  # outside agent's explicit approval signal

class ConvergenceResult(BaseModel):
    iterations: list[ConvergenceIteration]
    final_findings: list[Finding]  # findings with final statuses
    total_iterations: int
    exit_reason: Literal["all_verified", "max_iterations", "approved"]
    final_verdict: Literal["pass", "revise", "escalate"]
```

### 2.6 Expert Witness

**Module:** `agentcouncil/specialist.py`

Protocol-scoped bounded specialist consultation. Generic over protocol-owned Pydantic artifact types.

**Acceptance criteria:**

- [EW-01] `specialist.py` exposes `specialist_check(sub_question, context_slice, provider_config, artifact_cls)` that returns a typed artifact
- [EW-02] Specialist receives ONLY the targeted sub-question and a minimal context slice — never the full debate transcript
- [EW-03] Specialist output is classified as evidence, not a finding or decision — it does not alter protocol truth unless explicitly adopted in synthesis with citation
- [EW-04] One specialist check per protocol run by default (configurable via `max_specialist_checks` parameter)
- [EW-05] Trigger is caller- or protocol-controlled only — never automatic
- [EW-06] Protocol-specific output schemas owned by protocol, not by specialist.py:
  - Challenge: `ChallengeSpecialistAssessment(assumption, validity, evidence, confidence)`
  - Review: `ReviewSpecialistFinding(area, severity, evidence, affected_scope)`
  - Decide: `DecideSpecialistEvaluation(option_id, criterion, score, rationale)`
- [EW-07] Specialist output is evaluative, not prescriptive — output schema constrains against solutioning
- [EW-08] Specialist evidence is inserted into the transcript as a turn with `phase="specialist"` and full provenance
- [EW-09] `parent_turn_id` on the specialist turn links back to the exchange turn that triggered the check
- [EW-10] Specialist provider must be different from the main outside agent provider (enforced, not just encouraged)
- [EW-11] Protocol rollout order: challenge first, review second, decide third, brainstorm last
- [EW-12] New MCP tool parameter on protocol tools: `specialist_provider` (optional) to pre-configure the specialist backend
- [EW-13] If specialist call fails (provider error, parse failure), the protocol continues without specialist evidence — it's advisory, not blocking

### 2.7 Blind Panel

**Module:** Extends `agentcouncil/deliberation.py` topology

Sealed N-party proposals where multiple outside agents propose independently before reveal.

**Acceptance criteria:**

- [BP-01] Brainstorm and decide accept a `backends` parameter (list of profile names) for multi-agent mode
- [BP-02] Each outside agent receives the same clean brief — agents cannot see each other's proposals before simultaneous reveal
- [BP-03] All proposals are collected before any are revealed — sealed independence
- [BP-04] Synthesis handles N+1 proposals (N outside + 1 lead) with per-proposal provenance
- [BP-05] Each proposal turn in the transcript has distinct `actor_id`, `actor_provider`, `actor_model`
- [BP-06] Maximum 5 outside agents per panel (hard cap to control noise)
- [BP-07] Diversity-aware warning: system warns (does not block) when selected backends likely use correlated model families
- [BP-08] Diversity detection uses conformance certifier model metadata
- [BP-09] Exchange rounds after reveal: lead can address disagreements across N proposals
- [BP-10] Final artifact includes provenance for which proposal(s) influenced each point
- [BP-11] Protocol-specific applicability: brainstorm (highest value), decide (high), review (medium — finding dedup complex), challenge (lowest — adversarial noise risk)
- [BP-12] Single-backend mode (current behavior) remains the default — multi-agent is opt-in
- [BP-13] All proposals persisted in journal with full per-agent provenance
- [BP-14] If one agent fails, the panel continues with remaining agents — partial panel is valid if N-1 >= 1

### 2.8 Deliberation Inspector

**Module:** `agentcouncil/inspector.py`

CLI viewer for persisted journal entries. Read-only inspection, not participation.

**Acceptance criteria:**

- [DI-01] CLI command: `agentcouncil inspect <session_id>` renders formatted transcript
- [DI-02] Output shows: protocol type, status, each turn with actor identity/provider/model/phase/timestamp
- [DI-03] Independence phases clearly marked (who proposed blind vs. who saw context)
- [DI-04] Finding status progression displayed: open -> fixed -> verified (for convergence loop entries)
- [DI-05] Specialist evidence shown with provenance and source question
- [DI-06] Synthesis result and consensus status displayed
- [DI-07] `--watch` flag streams live events via Turn Stream cursors (polls at 2s intervals)
- [DI-08] `--json` flag outputs raw journal JSON instead of formatted display
- [DI-09] Uses Rich library for terminal rendering (already a dependency)
- [DI-10] Graceful handling of unknown session_id with actionable error message
- [DI-11] `agentcouncil inspect --list` shows recent sessions (delegates to `journal_list`)

---

## 3. Project Structure

```
agentcouncil/
  # Existing modules (modified)
  schemas.py          # TN: normalized transcript, provenance fields, convergence schemas
  deliberation.py     # TN: unified transcript, BP: N-party topology
  review.py           # CL: convergence loop integration point
  server.py           # DJ/TS/RP/CL/EW: new MCP tools, journal integration
  session.py          # No changes
  
  # New modules
  journal.py          # DJ + TS: persistence, event log, cursor retrieval
  workflow.py         # RP: protocol state machine, checkpointing, resume
  convergence.py      # CL: iterative review loop, finding status tracking
  specialist.py       # EW: bounded specialist consultation, provenance tagging
  inspector.py        # DI: CLI viewer, Rich rendering

  # Existing modules (unchanged)
  adapters.py         # Deprecated, no changes
  brief.py            # No changes
  certifier.py        # BP: diversity detection uses existing metadata
  config.py           # No changes
  challenge.py        # EW: specialist integration (phase 2)
  decide.py           # EW/BP: specialist + multi-agent (phase 3)
  providers/          # No changes
  runtime.py          # No changes

tests/
  # New test files
  test_journal.py     # DJ + TS tests
  test_workflow.py    # RP tests
  test_convergence.py # CL tests
  test_specialist.py  # EW tests
  test_inspector.py   # DI tests
  test_blind_panel.py # BP tests
  
  # Modified test files
  test_schemas.py     # TN: updated for normalized transcript
  test_deliberation.py # TN + BP: updated for unified transcript, N-party
  test_review.py      # CL: convergence integration tests

~/.agentcouncil/
  journal/            # DJ: one JSON file per session
    {session_id}.json
```

**Journal storage format: One JSON file per session.**

`~/.agentcouncil/journal/{session_id}.json` — one file per completed protocol run. Sessions are the natural unit of access, expected volume is low (tens to hundreds), human inspectability matters for a CLI tool, and atomic write (temp + rename) is trivial per-file.

---

## 4. Code Style

- **Language:** Python 3.12+
- **Models:** Pydantic v2 BaseModel for all data structures. Use `model_validator` for cross-field invariants (existing pattern in `schemas.py`)
- **Async:** All protocol engines and MCP tools are async. New modules follow the same pattern
- **Type hints:** Full type annotations on all public functions. Use `Optional[]` explicitly, not `| None` (matches existing codebase)
- **Imports:** `from __future__ import annotations` in every module (existing pattern)
- **Naming:** snake_case for modules and functions, PascalCase for classes, UPPER_CASE for module-level constants
- **Logging:** Use `logging.getLogger("agentcouncil.<module>")` (existing pattern)
- **Error handling:** Raise `ValueError` for invalid input, custom errors for provider/adapter failures. Never silently swallow errors
- **Tests:** pytest + pytest-asyncio. Mock-based by default, no live dependencies. Use `@pytest.mark.real` for integration tests
- **Dependencies:** No new dependencies. Use existing: Pydantic, FastMCP, Rich
- **Module exports:** `__all__` in every module (existing pattern)
- **Docstrings:** Google-style on public classes and functions. Include requirement IDs where applicable (existing pattern: `(REV-07)`)

---

## 5. Testing Strategy

### Unit tests (mock-based, no live dependencies)

| Test file | What it covers | Key scenarios |
|-----------|---------------|---------------|
| `test_journal.py` | Journal persistence, retrieval, listing | Write + read roundtrip, atomic write safety, schema versioning, listing with filters, unknown session_id |
| `test_journal.py` | Turn Stream events | Event append, cursor retrieval, since_cursor filtering, empty cursor returns all |
| `test_workflow.py` | Protocol state machine | Checkpoint at each phase boundary, resume from checkpoint, resume completed protocol (error), state serialization roundtrip |
| `test_convergence.py` | Convergence loop | Full loop (open->fixed->verified), max iterations exit, explicit approval exit, wont_fix flow, reopened finding, scoped re-review prompt construction, finding identity tracking |
| `test_specialist.py` | Expert Witness | Bounded brief construction, context isolation verification, typed output parsing, provider error graceful fallback, provenance tagging |
| `test_blind_panel.py` | Blind Panel | Sealed independence (no cross-proposal leakage), N+1 synthesis, partial panel on failure, diversity warning, max agent cap |
| `test_inspector.py` | CLI viewer | Formatted output for each protocol type, --json flag, --watch polling, --list delegation, unknown session_id |
| `test_schemas.py` | Transcript normalization | Normalized transcript construction, phase enum values, backward compat for BrainstormResult, provenance fields optional |

### Integration tests (`@pytest.mark.real`)

| Test | What it covers |
|------|---------------|
| `test_mcp_session.py` | Journal persistence through full MCP protocol run |
| `test_convergence.py` | End-to-end convergence loop with stub provider |

### What NOT to test

- Don't test Rich rendering output pixel-by-pixel — test that the inspector calls the right journal APIs
- Don't test filesystem atomicity of rename — trust the OS
- Don't test provider behavior — that's covered by existing provider tests

---

## 6. Boundaries

### Always do

- Persist journal entries for every completed protocol run
- Enforce atomic writes (temp file + rename)
- Maintain backward compatibility for existing artifact shapes
- Use existing `Finding.id` for convergence loop tracking
- Enforce specialist context isolation (bounded sub-question only)
- Enforce sealed independence in Blind Panel (no cross-proposal visibility before reveal)
- Version the journal schema from day one
- Keep protocol-specific schemas owned by protocol modules, not by shared infrastructure

### Ask first

- Before changing any existing MCP tool signatures (backward compat risk)
- Before adding new dependencies to `pyproject.toml`
- Before changing the `Finding` model fields (affects existing review consumers)
- Before implementing convergence for challenge or decide (review-only first)
- Before persisting any content that could contain secrets or credentials

### Never do

- Never persist API keys, tokens, or provider credentials in journal entries
- Never allow a specialist to see the full debate transcript
- Never allow Blind Panel agents to see each other's proposals before reveal
- Never allow infinite convergence loops (hard cap enforced)
- Never make specialist checks automatic (caller/protocol-controlled only)
- Never build a desktop application or interactive chat UI
- Never adopt the "join" metaphor where agents see accumulated session context
- Never build free-form multi-agent discussion — maintain structured protocols
- Never break existing one-shot protocol behavior — new features are additive

---

## 7. Dependency Order

```
Phase 1 (Foundation):
  [1. Deliberation Journal] + [2. Transcript Normalization]
  (coupled schema decisions — build together)

Phase 2 (Workflow):
  [3. Resumable Protocol State Model]
  (depends on Journal for checkpoint storage)

Phase 3 (Features — parallelizable):
  [4. Turn Stream]          (depends on Journal)
  [5. Convergence Loops]    (depends on Journal + Resumable State)

Phase 4 (Multi-agent):
  [6. Expert Witness]       (depends on Transcript Normalization)

Phase 5 (Expansion):
  [7. Blind Panel]          (depends on Transcript Normalization; Expert Witness is strategic sequencing, not hard dependency)

Phase 6 (Observability):
  [8. Deliberation Inspector] (depends on Journal + Turn Stream)
```

---

## 8. Open Design Decisions

These require resolution during implementation, not upfront:

1. **Resumable state representation:** Phase checkpoints vs. resumable jobs vs. general workflow state machine. Decide when implementing item 3.
2. **Transcript normalization strategy:** Unify brainstorm into existing `Transcript` model vs. create new journal-native schema. Decide when implementing item 2.
3. **Journal redaction:** How to handle sensitive content in persisted transcripts. Decide when implementing item 1.
4. **Convergence success criterion:** What "proven" means for the review-only MVP before extending to challenge/decide. Decide after shipping item 5.

---

## 9. Risks

1. **Schema evolution** — Turn-level provenance introduces migration needs. Start minimal, version explicitly.
2. **Specialist discipline** — Expert Witness could erode protocol discipline if schemas allow solutioning. Output schema must constrain.
3. **N-party noise** — Correlated model families produce duplicate viewpoints. Diversity warnings mitigate.
4. **Engine topology** — Current 2-party engines need non-trivial redesign for Blind Panel. Largest risk item.
5. **Persistence scope creep** — Over-designing the journal creates migration burden. Start with session + turns + artifact.
6. **Sensitive data persistence** — Journal writes code/artifacts to disk. Consider redaction/opt-out.
7. **Context cost expansion** — N-party + specialist + convergence multiply token usage. Summarization checkpoints and cost warnings needed.
8. **Observability gravity** — Building the viewer too early drives chat-room expectations. Protocol structure stays primary.
