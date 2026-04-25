# Changelog

## 0.3.0 (2026-04-14)

Second public release. This version expands AgentCouncil from one-shot deliberation protocols into a broader workflow system with persistent history, iterative review loops, richer provenance, and an autopilot workflow for governed delivery inside Claude Code.

### Features

- **Deliberation Journal:** Every protocol run auto-persists to `~/.agentcouncil/journal/` with atomic writes, schema versioning, and per-turn provenance. MCP tools: `journal_list`, `journal_get`
- **Turn Stream:** Append-only event log with cursor-based retrieval via `journal_stream` tool. File-locked appends prevent concurrent write races
- **Convergence Loops:** Iterative review workflow — findings → describe fix → scoped re-review → verify approach. Per-finding status tracking (open/fixed/verified/reopened/wont_fix). MCP tool: `review_loop`
- **Expert Witness (building blocks):** Bounded specialist consultation via `specialist_check()` and `make_specialist_turn()`. Protocol-specific typed output schemas. Advisory evidence with provenance tagging. Not yet automatically invoked during protocol execution — available as library API
- **Blind Panel:** Sealed N-party proposals via `brainstorm_panel()`. Multiple outside agents propose independently before reveal. Wired to `brainstorm` tool via `backends` parameter
- **Resumable Protocol State:** Protocol state machine with checkpointing at phase boundaries. Review protocol wired with checkpoint persistence during execution. MCP tool: `protocol_resume`
- **Deliberation Inspector:** CLI session viewer (`agentcouncil <session_id>`, `agentcouncil --list`, `--json`). New `/inspect` skill for in-session use
- **Enhanced /review skill:** Supports `--loop` / `--converge` flag for iterative convergence mode. Shows contextual hint after one-shot reviews with findings
- **Autopilot workflow:** New `/autopilot` Claude Code skill plus MCP autopilot tools for spec validation, tier classification, durable run state, status inspection, and resume (`autopilot_prepare`, `autopilot_start`, `autopilot_status`, `autopilot_resume`)
- **Transcript Normalization (partial):** `TranscriptTurn` extended with per-turn provenance fields (actor_id, actor_provider, actor_model, phase, timestamp, parent_turn_id). `BrainstormResult.transcript` migrated from `RoundTranscript` to `Transcript`. Exchange turns populated with provenance. Initial proposals and synthesis remain as top-level `Transcript` fields — full migration to turn-only representation deferred

### Schema additions

- `TurnPhase` literal type for transcript turn phases
- `JournalEntry` model for persistent session records
- `FindingStatus`, `FindingIteration`, `ConvergenceIteration`, `ConvergenceResult` for convergence loops
- `ChallengeSpecialistAssessment`, `ReviewSpecialistFinding`, `DecideSpecialistEvaluation` for specialist checks
- `ProtocolPhase`, `ProtocolCheckpoint` for resumable state

### Breaking Changes

- **`BrainstormResult.transcript` type changed from `RoundTranscript` to `Transcript`.** Code accessing `.brief_prompt`, `.outside_proposal`, `.lead_proposal`, or `.negotiation_output` must migrate to `.input_prompt`, `.outside_initial`, `.lead_initial`, and `.final_output` respectively. `RoundTranscript` is still importable but deprecated.

### Known Limitations

- **Convergence loops evaluate described changes, not actual file modifications.** The lead describes how it would fix findings; the re-review evaluates those descriptions against the original artifact. Actual file changes between iterations are not supported in the current MCP-based workflow.
- **Journal persistence overwrites prior checkpoint state.** Final `_persist_journal` call replaces the entry rather than merging, so mid-run checkpoints and events may be lost. Resume from `exchange_complete` phase restarts rather than continuing.
- **Turn Stream events are not automatically emitted during protocol execution.** `append_event()` exists as API but protocol engines don't call it yet.
- **Expert Witness `specialist_provider` parameter is accepted but not automatically invoked.** Use `specialist_check()` directly via the library API.
- **The low-level MCP autopilot path remains infrastructure-first.** The user-facing `/autopilot` skill is the best way to exercise the full workflow in Claude Code today; the typed MCP autopilot runners and gates are still evolving.

### Security

- Journal path traversal prevention via session_id regex validation and resolved-path containment check
- File-locked event appends prevent concurrent write races

### Deprecations

- `RoundTranscript` and `Exchange` classes — still importable but superseded by unified `Transcript`
- `TranscriptMeta` — envelope-level provenance superseded by per-turn provenance fields

## 0.1.0 (2026-04-13)

First public release.

### Features

- **Four deliberation protocols:** brainstorm, review, decide, challenge — each with distinct roles for Claude Code and the outside agent
- **Seven backend providers:** Claude (default), Codex, Ollama, OpenRouter, Bedrock, Kiro, plus StubProvider for testing
- **Provider capability metadata:** session_strategy, workspace_access, supports_runtime_tools — skills adapt automatically
- **Session API:** outside_start/outside_reply/outside_close for multi-turn deliberations
- **Named backend profiles** via `.agentcouncil.json` with precedence resolution
- **Auto-fallback** to Claude when no backend configured
- **Read-only tool harness** for workspace inspection by outside agents (path security, extension blocklist, token budget)
- **Conformance certification** for gated protocols (review, challenge)
- **Claude Code plugin** install via `/plugin marketplace add`
