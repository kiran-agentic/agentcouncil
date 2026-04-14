# Changelog

## 0.2.0 (2026-04-14)

### Features

- **Deliberation Journal:** Every protocol run auto-persists to `~/.agentcouncil/journal/` with atomic writes, schema versioning, and per-turn provenance. MCP tools: `journal_list`, `journal_get`
- **Turn Stream:** Append-only event log with cursor-based retrieval via `journal_stream` tool. File-locked appends prevent concurrent write races
- **Convergence Loops:** Iterative review workflow — findings → fix → scoped re-review → verify resolution. Per-finding status tracking (open/fixed/verified/reopened/wont_fix). MCP tool: `review_loop`
- **Expert Witness:** Bounded specialist consultation via `specialist_check()`. Protocol-specific typed output schemas. Advisory evidence with provenance tagging
- **Blind Panel:** Sealed N-party proposals via `brainstorm_panel()`. Multiple outside agents propose independently before reveal. Wired to `brainstorm` tool via `backends` parameter
- **Resumable Protocol State:** Protocol state machine with checkpointing at phase boundaries. Review protocol wired with checkpoint persistence during execution. MCP tool: `protocol_resume`
- **Deliberation Inspector:** CLI session viewer with `agentcouncil inspect` command. Supports `--list`, `--json`, `--watch` flags
- **Transcript Normalization:** Unified `Transcript` model with `TranscriptTurn` entries carrying per-turn provenance fields (actor_id, actor_provider, actor_model, phase, timestamp, parent_turn_id). `BrainstormResult.transcript` migrated from `RoundTranscript` to `Transcript`

### Schema additions

- `TurnPhase` literal type for transcript turn phases
- `JournalEntry` model for persistent session records
- `FindingStatus`, `FindingIteration`, `ConvergenceIteration`, `ConvergenceResult` for convergence loops
- `ChallengeSpecialistAssessment`, `ReviewSpecialistFinding`, `DecideSpecialistEvaluation` for specialist checks
- `ProtocolPhase`, `ProtocolCheckpoint` for resumable state

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
