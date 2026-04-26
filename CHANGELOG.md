# Changelog

## 0.3.1 (2026-04-26)

Patch release for the 0.3.0 autopilot workflow, focused on faster opt-in review gates and safer durable state.

### Features

- **Autopilot review speed controls:** `review_depth=fast|balanced|deep|legacy` and `lead_review_model=<model>` let users opt into faster review gates while preserving 0.3.0 legacy behavior by default.
- **ReviewContextPack:** New `autopilot_context_pack` MCP tool creates a sanitized, per-run context artifact and reuses distilled global project facts to reduce repeated reviewer discovery work.
- **Review observability:** `review_loop` records reviewer provenance, elapsed timing, budget, backend, lead review model, and blocked status into `autopilot_status`.
- **Manifest-driven project discovery:** Autopilot prep and context generation now detect common Python, JavaScript/TypeScript, Go, Rust, and test manifests instead of assuming Python-only projects.

### Fixes

- Balanced and fast review modes now surface provider failures as blocked states instead of silently falling back into a long legacy path.
- MCP provider adapters receive review-depth timeouts, preventing shorter review modes from being held by the old 900-second default.
- Workspace resolution walks past plugin-cache wrapper processes to find the real Claude Code project directory.
- Workspace resolution no longer falls back to the user home directory when project detection fails.
- Project-local autopilot state stores context-pack refs as project-relative paths to avoid leaking private absolute paths.
- `review_loop` can recover run ids from context-pack references, allowing durable review status updates during resumed autopilot runs.

### Security

- Context packs exclude `.mcp.json`, env files, Claude/Codex/Serena folders, dependency directories, and build outputs.
- Context-pack payloads redact common API keys, GitHub tokens, Google API keys, AWS access keys, AWS ARNs, signed URLs, JWT-like strings, secret-like assignments, and user home paths.

## 0.3.0 (2026-04-25)

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
- **Autopilot workflow:** New `/autopilot` Claude Code skill plus MCP autopilot tools for spec validation, tier classification, durable run state, skill-path checkpointing, status inspection, and resume (`autopilot_prepare`, `autopilot_checkpoint`, `autopilot_start`, `autopilot_status`, `autopilot_resume`)
- **Autopilot gate backend selection:** `/autopilot backend=<profile>` selects the outside reviewer backend for `review_loop` gates; `challenge_backend=<profile>` selects the outside attacker backend for challenge gates
- **Autopilot protocol durability:** `/autopilot` now records project-local run state under `docs/autopilot/` so resumed sessions know the next required gate instead of relying on conversation memory
- **Upgrade and reinstall guidance:** README now documents normal plugin updates, user-scope terminal updates, clean reinstall fallback, and cache-clearing fallback for stale plugin installs
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
- **The low-level MCP autopilot path remains infrastructure-first.** The user-facing `/autopilot` skill is the best way to exercise the full workflow in Claude Code today; the typed MCP autopilot runners are still evolving. Real typed-pipeline gate execution is available when `AGENTCOUNCIL_AUTOPILOT_GATES=1`; otherwise the typed pipeline uses stub gate artifacts for compatibility.

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
