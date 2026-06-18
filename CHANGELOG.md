# Changelog

## 0.6.1 (2026-06-18)

Native Cursor plugin support.

### Fixes

- **Installable as a Cursor plugin (fixes `No module named 'rich.traceback'` on Cursor plugin install).** Added a `.cursor-plugin/plugin.json` manifest so Cursor's "install from repo URL" launches the MCP server correctly. Previously Cursor had no native manifest and fell back to `.claude-plugin/plugin.json`, whose command uses `${CLAUDE_PLUGIN_ROOT}` — a variable Cursor does not set — so the server launched from a broken path and crashed on startup. The Cursor manifest uses a relative command (resolved from the plugin root) and sets `AGENTCOUNCIL_HOST=cursor`. `scripts/start-server.sh` now also honors `CURSOR_PLUGIN_ROOT` when present and anchors on its own location otherwise. Verified end-to-end: the server boots over MCP via a relative command with no `CLAUDE_PLUGIN_ROOT`.

## 0.6.0 (2026-06-18)

Self-configuration skill and a more robust server bootstrap.

### Features

- **`/configure` skill:** a new skill that sets up AgentCouncil's backends — it reads the current config (`show-effective-config`), detects which backends are available, and writes a valid `.agentcouncil.json` (profiles, default outside/lead backend, Cursor/Codex/Claude/Ollama/OpenRouter/Bedrock). API keys are never written to the file — `api_key_env` stores the env var *name*, enforced by the config validator. Available as `/configure` in Claude Code, Codex, and (via the generated command) Cursor.

### Fixes

- **Server bootstrap self-heals a partial/corrupt install.** `scripts/start-server.sh` previously trusted a venv that existed but was missing dependencies (e.g. a cold first install interrupted by an MCP host's startup timeout, a stale `.venv`, or `uv` absent from a minimal PATH), causing the server to crash with `No module named 'rich.traceback'`. It now decides whether to (re)install by actually importing `fastmcp`/`rich`/`pydantic`, repairs the env automatically (uv path verifies + `uv sync`/`--reinstall`; pip path verifies + reinstalls), discovers `uv` outside PATH, keeps pip/uv output off the MCP stdio stream, and emits a clear actionable error instead of a cryptic `ImportError`.

## 0.5.0 (2026-06-18)

Cursor host support and a host-aware default backend.

### Behavior changes

- **The default outside backend now follows the host.** On a **Codex** host the default outside agent (and library-mode lead) is now `codex` (previously `claude`); on **Cursor** it is `cursor`; on **Claude Code** it remains `claude`. Explicit `backend=`, `AGENTCOUNCIL_OUTSIDE_AGENT`, and a configured `default_profile` all still take precedence. If you relied on the implicit Codex-host + Claude-outside cross-backend pairing, set `AGENTCOUNCIL_OUTSIDE_AGENT=claude` (or a `default_profile`) to restore it.

### Features

- **Runs on Cursor:** AgentCouncil now runs natively in Cursor. Ships `.cursor/mcp.json` (registers the MCP server, sets `AGENTCOUNCIL_HOST=cursor`) and `.cursor/commands/*.md` slash commands for every skill (`brainstorm`, `challenge`, `decide`, `review`, `inspect`, `autopilot`), generated from the canonical `skills/*/SKILL.md` via `scripts/generate-cursor-commands.py`. See [docs/CURSOR.md](docs/CURSOR.md).
- **Host-aware default backend:** the default outside agent (and library-mode lead) is now **the host AgentCouncil runs under** — Claude Code → `claude`, Codex → `codex`, Cursor → `cursor` — falling back to `claude` when no host is identified. Host detection lives in `agentcouncil/host.py` (`AGENTCOUNCIL_HOST` env, then `CODEX_PLUGIN_ROOT`/`CLAUDE_PLUGIN_ROOT` markers). Explicit `backend=`, env vars, and `default_profile` still take precedence.
- **Cursor backend / model selection:** new `CursorProvider` (outside agent) runs the `cursor-agent` CLI in headless JSON print mode with native workspace access, using a stateless **replay** session strategy (full history re-sent each turn), plus `CursorAdapter` (lead, library mode). `--model` lets a deliberation use different Cursor models (e.g. `cursor-gpt5` vs `cursor-sonnet`) independent of the editor's model. `cursor` is now a valid outside and lead backend. Note: the `cursor-agent` CLI contract (flags, JSON shape, `--resume`) is doc-derived and not yet verified against a live binary — see [docs/CURSOR.md](docs/CURSOR.md).

### Docs

- New [docs/CURSOR.md](docs/CURSOR.md) setup guide.
- `docs/BACKENDS.md` documents the Cursor backend, the host-aware default, and Cursor as a lead, with updated precedence/capability tables.
- README documents Cursor as a host and the host-aware default.

## 0.4.0 (2026-05-03)

Feature release for configurable lead agents in MCP/library mode.

### Features

- **Configurable lead selection:** `brainstorm`, `review`, `decide`, `challenge`, `review_loop`, and `protocol_resume` now accept `lead_backend` and `lead_model`.
- **Native Claude/Codex leads:** the lead may be `claude`, `codex`, or a named profile whose provider is `claude` or `codex`. Claude preserves the historical `opus` default; Codex uses the CLI default unless a model is configured.
- **Independent outside backend selection:** `backend` continues to select the outside agent, and same-backend pairings are allowed with separate sessions.
- **Lead config defaults:** `.agentcouncil.json` supports `default_lead_profile`; env defaults are available via `AGENTCOUNCIL_DEFAULT_LEAD_PROFILE` and legacy `AGENTCOUNCIL_LEAD_AGENT`.
- **Autopilot gate lead wiring:** lower-level MCP autopilot tools persist `lead_backend`/`lead_model` and use them for real gate execution when `AGENTCOUNCIL_AUTOPILOT_GATES=1`.
- **Native Codex plugin packaging:** Added `.codex-plugin/plugin.json`, `.mcp.json`, and host-neutral shared skills so AgentCouncil can run directly as a Codex plugin with Codex as the host lead.

### Fixes

- Explicit built-in backend names such as `backend="claude"` now override `default_profile` instead of being swallowed by the configured default.
- Misspelled explicit backend/profile names now fail closed instead of silently falling through to defaults.
- `scripts/start-server.sh` now supports both Claude Code and Codex plugin environment variables.
- Real autopilot gate transcripts now record lead/outside backend, model, transport, workspace access, and independence tier metadata.
- Real review, challenge, and review_loop autopilot gates now apply certification checks.
- `review_loop` now escalates protocol `partial_failure` results instead of treating an empty failure artifact as a clean pass.
- Autopilot brainstorm gates now construct a valid `Brief` directly instead of calling `BriefBuilder` with unsupported arguments.

### Docs

- `docs/BACKENDS.md` documents lead selection separately from outside backend selection.
- `docs/ARCHITECTURE.md` documents configurable MCP/library leads and clarifies that Claude Code skill mode remains host-driven.
- Autopilot docs now describe the opt-in real-gate path and stored lead/outside gate settings.

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
