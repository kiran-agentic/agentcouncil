# Architecture

Technical design of AgentCouncil for contributors and advanced users. Throughout this document, "Claude Code" refers to the host environment that orchestrates protocols; "Claude" in protocol descriptions refers to Claude Code's role; the "outside agent" is a separate LLM session.

## How It Works

AgentCouncil runs as a Claude Code plugin. When you type `/brainstorm`, `/review`, `/decide`, or `/challenge`, Claude Code loads the skill instructions and executes the protocol step by step.

```
User types /brainstorm
     │
     ▼
Claude Code loads skills/brainstorm/SKILL.md
     │
     ▼
Claude follows the protocol steps:
  - Writes its own proposal (using full conversation context)
  - Sends neutral brief to outside agent via MCP tools
  - Reads outside agent's response
  - Exchanges and negotiates
  - Presents structured result
```

The outside agent is reached via MCP session tools:
- **`outside_start(prompt, profile?, model?)`** — opens a new session with an outside backend, returns `session_id`
- **`outside_reply(session_id, prompt)`** — continues an existing session
- **`outside_close(session_id)`** — closes the session and frees resources

## Three-Layer Architecture

The backend stack has three distinct layers with separate responsibilities:

```
OutsideProvider  (transport: chat_complete, auth_check)
OutsideRuntime   (tool loop: list_files, search_repo, read_file, read_diff)
OutsideSession   (lifecycle: open/call/close, message accumulation)
```

### OutsideProvider — Transport Layer

`OutsideProvider` is the abstract base class all backend implementations must satisfy. It handles authentication and raw LLM communication.

```python
class OutsideProvider(abc.ABC):
    @abc.abstractmethod
    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse: ...

    @abc.abstractmethod
    async def auth_check(self) -> None: ...

    async def close(self) -> None:
        """Optional cleanup (default no-op). Overridden by subprocess providers like KiroProvider."""
        ...
```

Concrete implementations: `CodexProvider`, `ClaudeProvider`, `OllamaProvider`, `OpenRouterProvider`, `BedrockProvider`, `KiroProvider`, `StubProvider` (tests).

#### Capability Metadata

Each provider declares class-level capability attributes that downstream consumers (skills, session layer) use to adapt behavior:

| Attribute | Values | Purpose |
|-----------|--------|---------|
| `session_strategy` | `"persistent"` or `"replay"` | Whether the provider maintains conversation state internally |
| `workspace_access` | `"native"`, `"assisted"`, or `"none"` | Whether the provider can read project files on its own |
| `supports_runtime_tools` | `True` or `False` | Whether the provider supports the read-only tool harness |

These attributes are class-level (not instance-level) so that the provider factory can introspect capabilities without instantiation. Skills call `get_outside_backend_info` to read these values and adapt prompt construction — for example, inlining file contents for providers with `workspace_access="none"` vs. skipping them for `workspace_access="native"`.

### OutsideRuntime — Tool Loop Layer

`OutsideRuntime` wraps an `OutsideProvider` and runs a tool execution loop. It is responsible for:

- **Per-turn character budget** — rejects message lists exceeding 100 KB serialized
- **Tool dispatch** — executes `list_files`, `search_repo`, `read_file`, `read_diff` tool calls from the model
- **Retry limit** — allows up to 3 tool call rounds per turn; strips tools on the 4th call to force a text response
- **Security** — validates all file paths before execution (see Read-Only Tool Harness below)
- **Textual action protocol** — opt-in fallback for models that don't support function calling

### OutsideSession — Lifecycle Layer

`OutsideSession` composes an `OutsideProvider` and `OutsideRuntime` into an open/call/close lifecycle. It manages message accumulation for replay-style multi-turn conversations.

```python
session = OutsideSession(provider, runtime, profile="my-profile", model="llama3")
await session.open()          # calls provider.auth_check()
response = await session.call(prompt)  # appends user msg, runs turn, appends response
await session.close()         # no-op for HTTP providers
```

Each `call()` appends the user message and assistant response to the internal history. How much of that history is sent to the provider depends on the provider's `session_strategy`:

- **Persistent** (`codex`, `claude`, `kiro`): Only the latest user message is sent each turn. The provider maintains conversation state internally (via MCP thread, CLI session-id, or ACP session).
- **Replay** (`ollama`, `openrouter`, `bedrock`): The full accumulated message history is sent every turn. The provider is stateless and needs replay for context.

This routing is transparent to callers — `session.call(prompt)` works identically regardless of strategy.

## Module Structure

```
agentcouncil/
  server.py          # FastMCP server — session tools + protocol tools + journal tools
  providers/
    __init__.py      # re-exports from base
    base.py          # OutsideProvider ABC, ProviderResponse, StubProvider
    ollama.py        # OllamaProvider
    openrouter.py    # OpenRouterProvider
    bedrock.py       # BedrockProvider
    kiro.py          # KiroProvider (ACP subprocess)
    codex.py         # CodexProvider (persistent MCP client)
    claude.py        # ClaudeProvider (resumed one-shot CLI)
  runtime.py         # OutsideRuntime — read-only tool loop
  session.py         # OutsideSession — lifecycle management
  config.py          # AgentCouncilConfig, ProfileLoader, BackendProfile
  certifier.py       # ConformanceCertifier, CertificationResult
  adapters.py        # AgentAdapter (DEPRECATED — compat shim only)
  schemas.py         # Pydantic models for protocol I/O + journal + convergence + specialist
  brief.py           # Brief preparation with contamination detection
  deliberation.py    # brainstorm engine + brainstorm_panel (Blind Panel)
  review.py          # review engine
  decide.py          # decide engine
  challenge.py       # challenge engine

  # v2.0 Deliberation Infrastructure
  journal.py         # Deliberation Journal — persistent sessions + Turn Stream events
  workflow.py        # Resumable Protocol State — checkpoint/resume at phase boundaries
  convergence.py     # Convergence Loops — iterative review workflow
  specialist.py      # Expert Witness — bounded specialist consultation
  inspector.py       # Deliberation Inspector — CLI session viewer

skills/              # Skill definitions (protocol instructions)
  brainstorm/SKILL.md
  review/SKILL.md
  decide/SKILL.md
  challenge/SKILL.md
```

The skill files are the primary interface. The Python package provides the MCP session tools, the four protocol tools, the journal/inspector tools, and the library-mode engines.

## MCP Tools

### Session Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `outside_start` | `(prompt, profile?, model?)` | Open new session, return `session_id` + first response |
| `outside_reply` | `(session_id, prompt)` | Continue existing session |
| `outside_close` | `(session_id)` | Close session, remove from registry |
| `get_outside_backend_info` | `(profile?, model?)` | Inspect backend capabilities without opening a session |

Sessions are stored in `_SESSIONS` — an in-process dict mapping UUID strings to `OutsideSession` instances. Sessions are not persisted across server restarts.

### Protocol Tools

The four deliberation functions are also exposed as MCP tools for library-mode use:

| Tool | Outside agent role | Optional params |
|------|--------------------|----------------|
| `brainstorm` | Independent proposal + negotiation | `backend=`, `backends=` (list for Blind Panel) |
| `review` | Independent evaluative critique | `backend=` |
| `decide` | Independent option assessment | `backend=` |
| `challenge` | Adversarial attack on a plan | `backend=`, `specialist_provider=` |

### Convergence Tools

| Tool | Purpose |
|------|---------|
| `review_loop` | Iterative review: findings → fix → scoped re-review → verify. Exits on all-verified, max iterations, or explicit approval |

### Journal & Observability Tools

| Tool | Purpose |
|------|---------|
| `journal_list(limit?, protocol?)` | List recent journal entries with metadata |
| `journal_get(session_id)` | Retrieve a full journal entry |
| `journal_stream(session_id, since_cursor?)` | Stream events with cursor-based pagination |
| `protocol_resume(session_id, profile?, model?)` | Resume a checkpointed protocol run |

### Legacy Tools

| Tool | Status | Purpose |
|------|--------|---------|
| `outside_query` | **DEPRECATED** — will be removed in a future release | Single-shot outside agent query; now a shim that routes through the provider pipeline |

`outside_query` was the original tool for reaching the outside agent. It is replaced by the session API (`outside_start` / `outside_reply` / `outside_close`). Calls to `outside_query` still work but the response includes a deprecation notice directing users to the session tools.

## Config System

Named backend profiles live in `.agentcouncil.json`. The config system uses a 5-level precedence stack.

**`BackendProfile`** — one entry in the profiles dict:
```json
{
  "provider": "ollama",
  "model": "llama3.1:8b",
  "endpoint": null,
  "api_key_env": null,
  "cli_path": null,
  "auth_token_env": null
}
```

`cli_path` and `auth_token_env` are used by the Kiro provider. `cli_path` overrides the default binary name; `auth_token_env` is reserved for future headless auth.

**`AgentCouncilConfig`** — pydantic-settings BaseSettings loading from:
1. `init kwargs` (skill_arg — highest)
2. `AGENTCOUNCIL_*` env vars
3. `.agentcouncil.json` in cwd (project config)
4. `~/.agentcouncil.json` (global config)
5. pydantic defaults

**`ProfileLoader.resolve()`** walks the stack and returns a `BackendProfile` or falls back to the legacy `resolve_outside_backend()` result.

**`_make_provider(profile, model)`** — factory function in `server.py`:
- Calls `ProfileLoader().resolve()` to get a `BackendProfile` or a legacy string result
- For string results `"codex"` or `"claude"`: checks binary presence with `shutil.which`, raises `ProviderError` if missing, instantiates the provider directly
- For `BackendProfile` results: dispatches by `bp.provider` — `ollama`, `openrouter`, `bedrock`, `kiro`, `codex`, `claude`
- All `codex` and `claude` dispatch points include `shutil.which` binary guards (4 total)
- When no backend is configured anywhere (`profile=None`, no env var, no config file): `resolve_outside_backend()` returns `"claude"`, so ClaudeProvider is the automatic default
- Uses lazy imports per branch to avoid `ImportError` for uninstalled provider SDKs
- Returns an `OutsideProvider` instance ready for `OutsideRuntime`

## Read-Only Tool Harness

`OutsideRuntime` exposes 4 read-only tools to the outside model:

| Tool | What it does |
|------|-------------|
| `list_files` | List files/directories at a path inside the workspace |
| `read_file` | Read a file's contents (max 50 KB, UTF-8 with replacement) |
| `search_repo` | Search workspace files for a regex pattern via `grep -rn` |
| `read_diff` | Return `git diff HEAD` for a path inside the workspace |

**Security model (assisted backends only — native backends use their own permissions):**

- **Path traversal prevention:** `os.path.realpath()` resolves both the workspace root and candidate path before boundary check — catches symlink escapes in addition to `..` traversal
- **File blocklist:** rejects `.env`, `.env.*`, `.netrc`, `.npmrc`, `.git-credentials`, `.pypirc`, SSH keys (`id_rsa`, `id_ed25519`, etc.), and certificate files (`.pem`, `.key`, `.p12`, `.pfx`, `.crt`, `.cer`, `.secret`)
- **Directory blocklist:** rejects paths through `.ssh/`, `.aws/`, `.docker/`, `.gnupg/`
- **Per-turn retry limit:** 3 tool call rounds per `run_turn()` call; on the 4th round, tools are stripped and the model must produce a text response
- **Character budget:** serialized message list capped at 100 KB per turn by default; raises `TokenBudgetExceeded` if exceeded

> **Note:** Native backends (Claude, Codex, Kiro) run as local processes with their own tool permissions. They can read and write files using their built-in tools. AgentCouncil does not restrict their capabilities. See [SECURITY.md](../SECURITY.md) for the full trust model.

**Textual action protocol (opt-in):**

For models that do not support native function calling, `OutsideRuntime` can parse text-based actions anchored to line start:

```
READ_FILE path=agentcouncil/server.py
LIST_FILES path=.
SEARCH_REPO pattern=OutsideProvider
READ_DIFF path=agentcouncil/
```

The regex is anchored to line start (`re.MULTILINE`) to prevent casual prose mentions from triggering dispatch. This is disabled by default (`allow_textual_protocol=False`).

## Transcript & Provenance

### Per-Turn Provenance (v2.0)

Every `TranscriptTurn` now carries optional provenance fields for audit and inspection:

```python
class TranscriptTurn(BaseModel):
    role: str                              # "outside", "lead", "director", "specialist"
    content: str
    source_refs: list[SourceRef] = []
    # v2.0 provenance fields (all Optional for backward compat)
    actor_id: Optional[str] = None         # unique agent identifier
    actor_provider: Optional[str] = None   # backend provider name
    actor_model: Optional[str] = None      # specific model used
    phase: Optional[TurnPhase] = None      # "brief", "proposal", "exchange", "synthesis", "specialist", "convergence"
    timestamp: Optional[float] = None      # epoch seconds
    parent_turn_id: Optional[str] = None   # for threading specialist evidence
```

Exchange turns in `run_deliberation()` are populated with `phase="exchange"`, provider/model from metadata, and timestamps. Brainstorm proposal turns use `phase="proposal"`.

### Envelope-Level Metadata (Deprecated)

`TranscriptMeta` provides envelope-level provenance and is retained for backward compatibility but superseded by per-turn fields:

```python
class TranscriptMeta(BaseModel):
    lead_backend: Optional[str] = None
    lead_model: Optional[str] = None
    outside_backend: Optional[str] = None
    outside_model: Optional[str] = None
    outside_transport: Optional[str] = None
    independence_tier: Optional[str] = None
    outside_provider: Optional[str] = None
    outside_profile: Optional[str] = None
    outside_session_mode: Optional[str] = None
    outside_workspace_access: Optional[str] = None
```

## v2.0 Deliberation Infrastructure

### Deliberation Journal

Every completed protocol run is automatically persisted to `~/.agentcouncil/journal/{session_id}.json`. Journal entries contain the full transcript, artifact, provenance metadata, execution events, and optional checkpoint state.

**Key properties:**
- **Atomic writes** — temp file + `os.replace()` prevents partial writes on crash
- **Lazy directory creation** — journal directory created on first write, not at import time
- **Path validation** — session IDs are validated with regex (`^[a-zA-Z0-9_\-]+$`) and resolved-path containment check to prevent traversal
- **Schema versioned** — every entry has `schema_version: "1.0"` for future migration

**Journal entry schema (`JournalEntry`):**
- `session_id`, `protocol_type`, `start_time`, `end_time`, `status`
- `artifact` (dict — serialized protocol artifact)
- `transcript` (Transcript with per-turn provenance)
- `events` (list — Turn Stream event log)
- `state` (dict — checkpoint for resumable protocols)

### Turn Stream

Append-only event log within each journal entry, with cursor-based retrieval:

- `append_event(session_id, event)` — appends with monotonic `event_id` and timestamp. Uses `fcntl` file locking to prevent concurrent write races
- `stream_events(session_id, since_cursor?)` — returns events since cursor position. Read-only, side-effect-free

Event types: `turn_added`, `phase_transition`, `status_change`, `specialist_evidence`, `finding_status_change`.

> **Note:** The Turn Stream API and storage are implemented, but protocol execution does not yet call `append_event()` during runs. Events can be appended programmatically; automatic event emission from protocol phases is planned for a future release.

### Resumable Protocol State

Protocols can checkpoint at phase boundaries and resume from the last checkpoint:

**Phase boundaries:** `brief_sent`, `proposals_received`, `exchange_complete`, `before_synthesis`, `completed`.

**How it works:**
1. Protocol tool creates a journal session at start via `_create_journal_session()`
2. `checkpoint_callback` is passed through the protocol engine to `run_deliberation()`
3. At each phase boundary, the callback merges new state (proposals, exchanges, round counts) into an accumulated `ProtocolCheckpoint`
4. `protocol_resume(session_id)` loads the checkpoint, injects `resume_state` into `run_deliberation()`, which skips completed phases

Currently wired for the review protocol. Other protocols will be added in future releases.

### Convergence Loops

Iterative review workflow that loops until findings are verified:

```
1. Initial review → produces findings with severities
2. Lead addresses findings → describes changes
3. Scoped re-review → checks prior findings + regressions (not full re-review)
4. Loop until: all verified, max iterations reached, or explicit approval
```

**Per-finding status tracking:** `open` → `fixed` → `verified` (or `reopened`, `wont_fix`).

**Finding identity:** Uses the existing `Finding.id` field. The outside agent assigns IDs; the system validates uniqueness, generates fallback IDs from title+severity hash when missing, and carries forward unmentioned IDs across iterations.

**Hard cap:** `MAX_ITERATIONS = 10` regardless of caller configuration. Default is 3.

### Expert Witness

Bounded specialist consultation for protocol sub-questions. The `specialist.py` module provides `specialist_check()` and `make_specialist_turn()` as reusable building blocks. A specialist agent receives only a targeted sub-question and minimal context slice (never the full debate), returns typed evaluative output, and the result can be inserted as provenance-tagged advisory evidence.

**Key properties:**
- Generic over protocol-owned Pydantic artifact types (`ChallengeSpecialistAssessment`, `ReviewSpecialistFinding`, `DecideSpecialistEvaluation`)
- Output is evaluative, not prescriptive — schemas constrain against solutioning
- Evidence is advisory — does not alter protocol truth unless adopted in synthesis with citation
- One check per run by default, caller/protocol-controlled trigger
- Graceful failure — returns `None` on error, protocol continues

> **Note:** The specialist module and schemas are implemented, and `challenge_tool` accepts a `specialist_provider` parameter, but automatic specialist invocation during protocol execution is not yet wired. Callers can use `specialist_check()` directly via the library API. Protocol integration is planned for a future release.

### Blind Panel

Sealed N-party proposals where multiple outside agents propose independently before reveal:

1. Each outside agent receives the same clean brief
2. All proposals collected via `asyncio.gather()` before reveal (sealed independence)
3. Structured synthesis across N+1 proposals with per-proposal provenance
4. Maximum 5 outside agents per panel

Exposed via `backends` parameter on `brainstorm` tool: `backends=["codex", "ollama-local"]`.

Partial panel on failure: if one agent fails, the panel continues with remaining agents (valid if N-1 >= 1).

### Deliberation Inspector

CLI viewer for persisted journal entries:

```bash
agentcouncil inspect <session_id>        # Formatted transcript with provenance
agentcouncil inspect --list              # Recent sessions
agentcouncil inspect <session_id> --json # Raw JSON
agentcouncil inspect <session_id> --watch # Stream live events
```

Renders protocol type, status, turns with actor identity/provider/model/phase/timestamp, independence markers, finding status progression, specialist evidence, and synthesis results.

## Migration from AgentAdapter

`AgentAdapter` is **deprecated**. It still works for backward compatibility but triggers a `DeprecationWarning` at class definition time. New backends should implement `OutsideProvider`.

**Old pattern (deprecated):**
```python
# Deprecated pattern:
class MyProvider(AgentAdapter):
    def call(self, prompt: str) -> str:
        ...  # synchronous string in/out

adapter = resolve_outside_adapter(backend="my-provider")
```

**New pattern:**
```python
# Current pattern:
class MyProvider(OutsideProvider):
    async def chat_complete(self, messages, tools=None) -> ProviderResponse: ...
    async def auth_check(self) -> None: ...
```

Register the provider in `.agentcouncil.json`:
```json
{
  "profiles": {
    "my-provider": {
      "provider": "my-provider",
      "model": "my-model"
    }
  }
}
```

Then add a branch in `_make_provider()` in `server.py` to instantiate it.

Note: The built-in provider strings `codex` and `claude` are dispatched directly by `_make_provider` — custom providers still need a branch added.

**Backward compat shim:** `OutsideSessionAdapter` wraps `OutsideSession` behind the `AgentAdapter` interface so existing `run_deliberation()` callers (which expect `AgentAdapter.acall()`) continue working without changes.

## Protocol Design

Each protocol gives Claude Code and the outside agent **distinct roles**:

| Protocol | Claude Code | Outside Agent |
|----------|-------------|--------------|
| **brainstorm** | Proposes first (full context) | Proposes independently (brief only), then they negotiate |
| **review** | Frames what to review, responds to findings | Reviews independently, produces findings |
| **decide** | Defines options and criteria, adds context | Evaluates each option independently |
| **challenge** | Defends the plan with evidence | Attacks assumptions, finds failure modes |

Only brainstorm has bilateral independence (both propose blind). The other three have Claude Code in a specific role — framer, definer, or defender — not duplicating the outside agent's work.

## Library Mode (Secondary)

The Python package also exposes full protocol tools via MCP (`brainstorm`, `review`, `decide`, `challenge` tools in `server.py`). These use a different execution model: the lead is a CLI subprocess with no conversation context, and outside agents use the `OutsideSession`/`OutsideRuntime` stack. Library mode is functional but secondary — skill mode is the primary interface. PROTOCOLS.md describes skill-mode behavior.

Key difference: In library-mode brainstorm, the outside agent proposes first and the lead reacts (outside-first). In skill mode, Claude proposes first with full context (lead-first). A future release may unify the protocol semantics between the two modes.

## Key Design Decisions

- **Skills are the primary interface** — they leverage Claude Code's full conversation context
- **Providers inside functions via lazy imports** — prevents `ImportError` when optional SDK extras aren't installed
- **Contamination detection** — briefs are scanned for opinion language before sending to the outside agent
- **Read-only tool surface for assisted backends** — Ollama, OpenRouter, and Bedrock can inspect the workspace but cannot modify it via the `OutsideRuntime` harness. Native backends (Claude, Codex, Kiro) use their own tool permissions
- **Independence before convergence** — in brainstorm, both agents propose blind. In other protocols, Claude Code provides a directed brief (what to review, which options to evaluate, what plan to attack) but the outside agent forms its response without seeing Claude Code's internal reasoning or preferences
- **`OutsideProvider` is the extension point** — `AgentAdapter` is a deprecated compat shim, not the extension point for new backends
