# Backends

AgentCouncil supports multiple AI backends as the outside agent. The active host agent — Claude Code, Codex, or Cursor — orchestrates the deliberation; the outside agent is a separate LLM session. This page explains how to select backends, configure profiles, and understand capability differences.

> **Host-aware default:** when nothing is configured, the default backend is **the host AgentCouncil runs under** — Claude Code → `claude`, Codex → `codex`, Cursor → `cursor`. See [Host-Aware Default](#host-aware-default) and, for Cursor specifically, [CURSOR.md](CURSOR.md).

## Selecting a Backend

### Per-invocation (skill argument)

Pass `backend=profile_name` to any skill command to use a specific profile for that call:

```
/brainstorm backend=local-llama How should we handle caching?
/review backend=openrouter-claude this implementation
/decide backend=bedrock-sonnet between these three options
```

### Profile config (project or global)

Create `.agentcouncil.json` in your project root (or `~/.agentcouncil.json` for global defaults):

```json
{
  "default_profile": "local-llama",
  "profiles": {
    "local-llama": {
      "provider": "ollama",
      "model": "llama3.1:8b"
    },
    "openrouter-claude": {
      "provider": "openrouter",
      "model": "anthropic/claude-3-5-sonnet",
      "api_key_env": "OPENROUTER_API_KEY"
    },
    "bedrock-sonnet": {
      "provider": "bedrock",
      "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    }
  }
}
```

### Environment variables

```bash
# Select a named profile as default (recommended)
export AGENTCOUNCIL_DEFAULT_PROFILE=local-llama

# Or use the legacy backend string (still supported)
export AGENTCOUNCIL_OUTSIDE_AGENT=claude

# Select the MCP/library-mode lead agent independently
export AGENTCOUNCIL_DEFAULT_LEAD_PROFILE=codex-lead
export AGENTCOUNCIL_LEAD_AGENT=codex
```

`AGENTCOUNCIL_DEFAULT_PROFILE` selects a named profile from your config file. `AGENTCOUNCIL_OUTSIDE_AGENT` is the legacy env var — it selects a backend by string name (e.g., `codex`, `claude`) without profile config. Both are supported; the named profile takes precedence when no explicit backend/profile is passed.

Lead selection is separate from outside-agent selection. The MCP/library protocol tools accept `lead_backend=` and `lead_model=` for the lead-side CLI adapter. `lead_backend` may be `claude`, `codex`, `cursor`, or a named profile whose provider is one of those; other providers remain outside-agent only. (In normal skill mode the lead is simply the host agent running the skill, so a lead adapter is only built in library/MCP mode.)

### Precedence

| Level | Source | Example |
|-------|--------|---------|
| 1 (highest) | explicit named profile | `backend=local-llama` in skill command |
| 2 | explicit built-in backend | `backend=claude` or `backend=codex` |
| 3 | env vars | `AGENTCOUNCIL_DEFAULT_PROFILE=local-llama` |
| 4 | project config | `.agentcouncil.json` in current directory |
| 5 | global config | `~/.agentcouncil.json` |
| 6 | legacy env var | `AGENTCOUNCIL_OUTSIDE_AGENT=claude` |
| 7 | host default | the backend it runs on (`claude` / `codex` / `cursor`) |
| 8 (default) | built-in default | `"claude"` (when no host is identified) |

Explicit built-in backend names intentionally bypass `default_profile`. For example, if `.agentcouncil.json` sets `default_profile="codex-outside"`, a tool call with `backend="claude"` still uses Claude.

### Host-Aware Default

When no backend is selected by any of levels 1–6, AgentCouncil defaults to **the host platform it is running under** — Claude Code → `claude`, Codex → `codex`, Cursor → `cursor`. This makes a zero-config deliberation use "the backend it runs on" (a fresh, independent session of the host model), so AgentCouncil works out of the box on every host without requiring a separate CLI.

The host is detected from `AGENTCOUNCIL_HOST` (set explicitly by each platform's MCP launch config — e.g. `.cursor/mcp.json` sets it to `cursor`), falling back to the `CODEX_PLUGIN_ROOT` / `CLAUDE_PLUGIN_ROOT` markers the Codex and Claude Code plugin runtimes already inject, and finally to `claude`. Because the host default sits *below* explicit config (levels 1–6), any `backend=`, env var, or `default_profile` you set still wins.

Lead precedence is similar but intentionally ignores outside defaults:

| Level | Source | Example |
|-------|--------|---------|
| 1 (highest) | tool arg | `lead_backend=codex` |
| 2 | env var | `AGENTCOUNCIL_DEFAULT_LEAD_PROFILE=codex-lead` |
| 3 | project config | `default_lead_profile` in `.agentcouncil.json` |
| 4 | global config | `default_lead_profile` in `~/.agentcouncil.json` |
| 5 | legacy env var | `AGENTCOUNCIL_LEAD_AGENT=codex` |
| 6 | host default | the backend it runs on (`claude` / `codex` / `cursor`) |
| 7 (default) | built-in default | `"claude"` with model `"opus"` (when no host is identified) |

## Available Backends

| Backend | Install | Required Env Vars | Provider Class |
|---------|---------|------------------|----------------|
| claude (default) | Claude CLI on PATH; already available in Claude Code | none | `ClaudeProvider` |
| **codex** | `codex` CLI on PATH | none | `CodexProvider` |
| **cursor** | `cursor-agent` CLI ([cursor.com/docs/cli](https://cursor.com/docs/cli)) | none (`cursor-agent login` or `CURSOR_API_KEY`) | `CursorProvider` |
| **ollama** | `pip install "agentcouncil[ollama]"` | none (local) | `OllamaProvider` |
| **openrouter** | `pip install "agentcouncil[openrouter]"` | `OPENROUTER_API_KEY` | `OpenRouterProvider` |
| **bedrock** | `pip install "agentcouncil[bedrock]"` | AWS credentials (boto3 chain) | `BedrockProvider` |
| **kiro** | `kiro-cli` on PATH ([kiro.dev/cli](https://kiro.dev/cli/)) | `kiro-cli auth login` (interactive) | `KiroProvider` |
| **all backends** | `pip install "agentcouncil[all-backends]"` | varies by provider | — |

## Provider Setup

### Ollama (local)

Ollama runs models locally — no API keys required.

**Install:**
```bash
pip install "agentcouncil[ollama]"
# Also install Ollama: https://ollama.com/download
ollama pull llama3.1:8b
```

**Profile config:**
```json
{
  "profiles": {
    "local-llama": {
      "provider": "ollama",
      "model": "llama3.1:8b"
    }
  }
}
```

**Required env vars:** None. Ollama runs at `http://localhost:11434` by default. Override with `endpoint` in the profile:
```json
{ "provider": "ollama", "model": "mistral", "endpoint": "http://my-host:11434" }
```

**Quick test:**
```
/brainstorm backend=local-llama What are the tradeoffs between REST and GraphQL?
```

---

### OpenRouter

OpenRouter proxies 100+ models from a single API endpoint.

**Install:**
```bash
pip install "agentcouncil[openrouter]"
```

**Required env vars:**
```bash
export OPENROUTER_API_KEY=sk-or-...
```

**Profile config:**
```json
{
  "profiles": {
    "openrouter-gpt": {
      "provider": "openrouter",
      "model": "openai/gpt-4o",
      "api_key_env": "OPENROUTER_API_KEY"
    }
  }
}
```

The `api_key_env` field stores the **name** of the env var, never the raw key.

**Quick test:**
```
/brainstorm backend=openrouter-gpt How should we structure our API?
```

---

### Amazon Bedrock

Bedrock provides access to AWS-hosted models via the standard boto3 credential chain.

**Install:**
```bash
pip install "agentcouncil[bedrock]"
```

**Required env vars:** Standard AWS credentials — any of:
- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_REGION`
- AWS profile via `~/.aws/credentials`
- IAM role (EC2, Lambda, ECS task role)

**Profile config:**
```json
{
  "profiles": {
    "bedrock-sonnet": {
      "provider": "bedrock",
      "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    }
  }
}
```

**Quick test:**
```
/review backend=bedrock-sonnet this authentication module
```

---

### Kiro (CLI)

Kiro connects via the Agent Communication Protocol (ACP), running kiro-cli as a persistent subprocess. Unlike HTTP-based providers, Kiro maintains a stateful session — the same kiro-cli process handles the full deliberation turn.

**Install:**
```bash
# Install kiro-cli: https://kiro.dev/cli/
kiro-cli auth login
```

**Required env vars:** None — Kiro uses interactive browser-based authentication via `kiro-cli auth login`. Credentials are stored locally in a SQLite database. AgentCouncil checks these paths in order:
1. `$XDG_DATA_HOME/kiro-cli/data.sqlite3` (if `XDG_DATA_HOME` is set)
2. `~/.local/share/kiro-cli/data.sqlite3` (Linux default)
3. `~/Library/Application Support/kiro-cli/data.sqlite3` (macOS)

> **Note:** Kiro does not yet support headless/CI authentication. There is no `KIRO_AUTH_TOKEN` environment variable — you must run `kiro-cli auth login` interactively on each machine. This is an upstream limitation (kirodotdev/Kiro#5938). The `auth_token_env` profile field is reserved for future use when upstream support lands.

**Profile config:**
```json
{
  "profiles": {
    "kiro": {
      "provider": "kiro",
      "cli_path": "kiro-cli"
    }
  }
}
```

Note that `cli_path` is optional — defaults to `kiro-cli` from PATH. The `auth_token_env` field is reserved for future headless auth.

**Quick test:**
```
/brainstorm backend=kiro How should we handle caching?
```

---

### Claude (CLI — default)

Claude is the default backend when running inside Claude Code — no configuration needed. ClaudeProvider uses `claude --print --session-id` on the first call to create a session, then `--resume` on subsequent calls to continue it, giving it persistent conversation state across turns.

**Install:** Already available inside Claude Code. For standalone use, install the [Claude CLI](https://docs.anthropic.com/en/docs/claude-code).

**Required env vars:** None.

**Profile config:** Not needed — Claude is the automatic default. To create an explicit profile:
```json
{
  "profiles": {
    "claude-explicit": {
      "provider": "claude"
    }
  }
}
```

**Quick test:**
```
/brainstorm How should we handle caching?
```
No `backend=` argument needed — Claude is the default.

---

### Codex (CLI)

Codex connects via a persistent MCP session — AgentCouncil's CodexProvider is an MCP client that launches `codex mcp-server` as a subprocess.

**Install:**
```bash
npm install -g @openai/codex
```

**Required env vars:** None — Codex uses its own authentication. Ensure the `codex` binary is on PATH.

**Profile config:**
```json
{
  "profiles": {
    "codex": {
      "provider": "codex"
    }
  }
}
```

**Quick test:**
```
/brainstorm backend=codex What are the tradeoffs of microservices vs monolith?
```

---

### Cursor (CLI)

Cursor runs the outside agent via the `cursor-agent` CLI in headless print mode (`--print --output-format json`). It uses a stateless **replay** session strategy — the full conversation is re-sent each turn — so context is preserved without relying on `cursor-agent`'s `--resume` (which was not verified against a live binary during development). Cursor is also the **zero-config default backend when the host is Cursor** — see [CURSOR.md](CURSOR.md) for the full host setup (MCP config + slash commands).

**Install:**
```bash
# install the Cursor CLI — https://cursor.com/docs/cli
cursor-agent login          # or export CURSOR_API_KEY=...
cursor-agent --list-models  # see which models you can pass as `model`
```

**Required env vars:** None when authenticated via `cursor-agent login`; otherwise `CURSOR_API_KEY`.

**Profile config** — name a profile per model so deliberations can pit one Cursor model against another:
```json
{
  "profiles": {
    "cursor-gpt5":   { "provider": "cursor", "model": "gpt-5" },
    "cursor-sonnet": { "provider": "cursor", "model": "sonnet-4.5" }
  }
}
```

**Quick test:**
```
/brainstorm backend=cursor-gpt5 What are the tradeoffs of microservices vs monolith?
```
On a Cursor host, plain `/brainstorm …` already uses Cursor (the host default) with the CLI's default model.

## Independence Tiers

AgentCouncil's core principle is **independence before convergence**. The value of that independence varies by which backend you choose.

### Cross-backend (highest diversity)

Different model families with different training data and different biases:

- `codex` (GPT family) + Claude Code host
- `claude` + Codex host
- `bedrock` with a non-Claude model + Claude Code or Codex host
- `openrouter` with a non-Claude model + Claude Code or Codex host
- `kiro` (Kiro family) + Claude Code or Codex host

Maximum cognitive diversity. Truly independent failure modes. **Recommended for:** high-stakes decisions, architectural choices, security reviews.

### Same-backend fresh session (protocol independence only)

Same model family, potentially correlated biases — but protocol independence is preserved (separate sessions, no shared context):

- `claude` subprocess + Claude Code host
- `codex` subprocess + Codex host
- `cursor` (a fresh `cursor-agent` session) + Cursor host — the zero-config default on Cursor
- `ollama` with a model derived from the same family as the host

**Recommended for:** lower-stakes work, speed-sensitive tasks, fully local environments.

**Note:** Ollama with a non-Claude model (e.g. `llama3`, `mistral`, `gemma`) counts as cross-backend — different model family = more diverse proposals.

### How Independence Varies by Protocol

| Protocol | Host agent's role | Outside agent's role | Backend matters because... |
|----------|--------------|---------------------|---------------------------|
| **brainstorm** | Proposes independently | Proposes independently | Different model = more diverse proposals |
| **review** | Frames the review question | Reviews independently | Different model = catches different issues |
| **decide** | Defines options and criteria | Evaluates each option | Different model = different risk assessment |
| **challenge** | Defends the plan | Attacks assumptions | Different model = finds different failure modes |

Cross-backend is most valuable for brainstorm and challenge, where cognitive diversity directly produces better outcomes.

## Workspace Access

Workspace access determines whether the outside agent can read project files during deliberation. The two access levels have different trust models — see [SECURITY.md](../SECURITY.md) for details.

| Backend | Access Level | Mechanism | Trust Model |
|---------|-------------|-----------|-------------|
| **codex** | Native | Persistent MCP session — reads files directly | Local process, own permissions |
| **kiro** | Native | Persistent ACP session — manages own tools | Local process, own permissions |
| **claude** | Native | Persistent session via `--session-id` — own workspace tools | Local process, own permissions |
| **cursor** | Native | `cursor-agent` reads files itself (stateless replay each turn) | Local process, own permissions |
| **ollama / openrouter / bedrock** | Assisted | Read-only tool harness: `list_files`, `search_repo`, `read_file`, `read_diff` | Restricted by AgentCouncil |

**Native backends** run as local processes with their own tool permissions. They can read and write files using their built-in tools. AgentCouncil does not restrict their capabilities.

**Assisted backends** use AgentCouncil's read-only tool harness (`OutsideRuntime`). The outside agent may call up to 4 read-only tools per turn, with a 3-retry limit. Security constraints:

- Path traversal and symlink escapes blocked via `os.path.realpath()`
- File blocklist rejects `.env`, `.env.*`, `.netrc`, `.npmrc`, `.git-credentials`, SSH keys, certificate files, and similar secrets
- Directory blocklist rejects paths through `.ssh/`, `.aws/`, `.docker/`, `.gnupg/`
- Per-turn character budget (100 KB default) caps context size

> **Note:** Assisted backends (OpenRouter, Bedrock) transmit file contents to remote APIs. The blocklist prevents reading obvious secrets, but workspace files sent to these backends leave your machine.

### Session Strategy

Session strategy determines how conversation history is managed between the session layer and the provider.

| Backend | Strategy | Behavior |
|---------|----------|----------|
| **codex** | Persistent | Provider maintains conversation state internally; only the latest message is sent each turn |
| **claude** | Persistent | Provider maintains conversation state via `--session-id`; only the latest message is sent each turn |
| **cursor** | Replay | Provider is stateless; full accumulated history is re-sent each turn (does not rely on `--resume`) |
| **kiro** | Persistent | Provider maintains conversation state via ACP; only the latest message is sent each turn |
| **ollama** | Replay | Provider is stateless; full accumulated history is sent every turn |
| **openrouter** | Replay | Provider is stateless; full accumulated history is sent every turn |
| **bedrock** | Replay | Provider is stateless; full accumulated history is sent every turn |

Persistent providers are more token-efficient for multi-turn deliberations. Replay providers work with any stateless HTTP endpoint but resend the full conversation each turn.

## Autopilot Gate Backends

The `/autopilot` skill accepts gate backend overrides:

```text
/autopilot backend=openrouter-gpt challenge_backend=bedrock-sonnet Add audit logging
```

- `backend=<profile>` selects the outside reviewer backend for every `review_loop` gate.
- `challenge_backend=<profile>` selects the outside attacker backend for the `challenge` gate.
- If `challenge_backend` is omitted, it defaults to `backend`.
- If both are omitted, AgentCouncil uses the configured default profile.

Model selection is done through named profiles. Put the model in `.agentcouncil.json` or `~/.agentcouncil.json`, then reference the profile by name:

```json
{
  "profiles": {
    "openrouter-gpt": {
      "provider": "openrouter",
      "model": "openai/gpt-4o",
      "api_key_env": "OPENROUTER_API_KEY"
    }
  }
}
```

The normal `/autopilot` spec, plan, build, verify, and ship steps run on the active host model. AgentCouncil selects models for independent review/challenge gate sessions. In the lower-level MCP autopilot runner, real gates can also set `lead_backend`/`lead_model` so review/challenge gate deliberations use Codex or Claude as the lead-side CLI adapter.

The lower-level `autopilot_prepare` tool also stores `review_backend`, `challenge_backend`, `lead_backend`, and `lead_model` in run state. When `AGENTCOUNCIL_AUTOPILOT_GATES=1` enables real gate execution for the typed MCP pipeline, `autopilot_start` and `autopilot_resume` use those stored gate settings. Without that flag, the typed pipeline continues to use stub gate artifacts for compatibility.

## Conformance Certification

Before using a model for review or challenge, AgentCouncil checks whether it has been certified to support function calling (tool use).

- **Certified models** unlock all 4 protocols: brainstorm, review, decide, challenge
- **Uncertified models** pass with a warning — absence of evidence is not evidence of absence
- **Prompt-only models** (no tool use support) are blocked from review and challenge, which require the read-only tool harness

Certification is done by `ConformanceCertifier` and results are cached in `~/.agentcouncil/certifications.json`. A model is checked the first time it is used for a gated protocol; the result is cached and reused on subsequent calls.

Certification happens automatically on first use of a gated protocol — no manual step needed. Stale certifications (from an older AgentCouncil version) warn to stderr but do not block execution — they are re-certified automatically.

> **Note:** Conformance certification applies to protocol tools (brainstorm, review, decide, challenge). Lower-level autopilot gates use stub artifacts unless `AGENTCOUNCIL_AUTOPILOT_GATES=1` is set; with real gates enabled, review and challenge gate sessions go through the same protocol/certification path as direct tool calls.

## Auto-Fallback

When no backend is configured anywhere (no profile, no env var, no `default_profile` in config), AgentCouncil defaults to **the host it runs under** — Claude Code → Claude, Codex → Codex, Cursor → Cursor — and to ClaudeProvider when no host can be identified. This means deliberations work out of the box on every supported host with zero configuration. See [Host-Aware Default](#host-aware-default).

**Explicit backend with missing binary:** If you request a specific backend (e.g., `backend=codex`) but the binary is not on PATH, AgentCouncil raises an error with installation instructions rather than silently falling back to another backend. This prevents accidental use of a different model family than intended.
