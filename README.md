<div align="center">

# AgentCouncil

**Multi-agent deliberation protocols for AI coding assistants.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](LICENSE)
[![Tests](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml/badge.svg)](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml)

Newest in `0.6.1`: **native Cursor plugin support** — install AgentCouncil directly from the repo URL in Cursor (`0.6.0` added the `/configure` skill and a self-healing server bootstrap).

AgentCouncil now runs natively in **Cursor** — alongside Claude Code and Codex — via a Cursor MCP config and generated slash commands. The **default outside backend follows the host you run on** (Claude Code → Claude, Codex → Codex, Cursor → Cursor), so deliberations work out of the box on every host, and on Cursor you can point the outside agent at any **Cursor model** (e.g. `gpt-5` vs `sonnet-4.5`).

Underneath that headline feature, AgentCouncil still provides its core multi-agent protocols: `/brainstorm`, `/review`, `/decide`, `/challenge`, and `/inspect`. The host agent — Claude Code, Codex, or Cursor — works with an outside agent that stays independent by role, backend, and session. The outside agent defaults to **the host you run on** (Claude Code → Claude, Codex → Codex, Cursor → Cursor), or you can configure Cursor models, Codex, Ollama, OpenRouter, Bedrock, or Kiro for cross-model diversity. See [CURSOR.md](docs/CURSOR.md) for running on Cursor.

</div>

---

## What's New In 0.6.0

This release adds a self-configuration skill and hardens the server bootstrap:

- **`/configure` skill:** set up AgentCouncil from inside the agent — it reads your current config, detects which backends are available, and writes a valid `.agentcouncil.json` (profiles + default outside/lead backend) for Cursor models, Codex, Claude, Ollama, OpenRouter, or Bedrock. API keys are never written to the file (`api_key_env` holds the env var *name*).
- **Self-healing bootstrap:** `scripts/start-server.sh` now verifies and repairs a partial/corrupt dependency install instead of crashing the MCP server with `No module named 'rich'` — fixing intermittent startup failures (notably the first launch inside Cursor).

### Previously in 0.5.0

This release brings AgentCouncil to **Cursor** and makes the default backend host-aware:

- **Runs natively in Cursor:** ships `.cursor/mcp.json` and generated `.cursor/commands/*.md` slash commands (one per skill), so `/brainstorm`, `/review`, `/decide`, `/challenge`, `/inspect`, and `/autopilot` work inside Cursor. See [CURSOR.md](docs/CURSOR.md).
- **Host-aware default backend:** the default outside agent (and library-mode lead) is now *the backend it runs on* — Claude Code → `claude`, Codex → `codex`, Cursor → `cursor` — falling back to `claude` when no host is identified. Explicit `backend=`, env vars, and `default_profile` still win. (Behavior change for Codex hosts — see [CHANGELOG.md](CHANGELOG.md).)
- **Cursor model selection:** a new `cursor` backend runs the `cursor-agent` CLI; name profiles like `cursor-gpt5` / `cursor-sonnet` to use different Cursor models per deliberation, independent of the editor's model.

### Previously in 0.4.0

Lead-agent selection became first-class in MCP/library mode:

- **Configurable lead agent:** `brainstorm`, `review`, `decide`, `challenge`, `review_loop`, and `protocol_resume` accept `lead_backend=` and `lead_model=`.
- **Native lead adapters:** `lead_backend` may be `claude`, `codex`, or a named profile backed by one of those native CLI providers. Claude still defaults to `opus`; Codex uses the Codex CLI default unless configured.
- **Independent outside selection:** `backend` continues to select the outside agent. Same-backend pairings are allowed with separate sessions and recorded as `same_backend_fresh_session`.
- **Autopilot gate wiring:** lower-level MCP autopilot runs persist `lead_backend`/`lead_model` and use them for real gate execution when `AGENTCOUNCIL_AUTOPILOT_GATES=1`.
- **Native Codex plugin surface:** `.codex-plugin/plugin.json` and `.mcp.json` let Codex load AgentCouncil skills and MCP tools directly. Skill wording is host-neutral so Codex and Claude Code can both be the lead in skill mode.
- **Release hardening:** explicit unknown backend/profile names now fail closed, real gate transcripts carry lead/outside provenance, real review/challenge/review_loop gates run certification checks, and partial review failures escalate instead of passing.

The `0.3.x` series added the current **`/autopilot`** workflow foundation:

- **`/autopilot`** is the governed implementation skill for Claude Code with spec, planning, build, review, verification, and ship stages.
- **`0.3.1` patch:** adds opt-in faster review gates with `review_depth=fast|balanced`, sanitized `ReviewContextPack` artifacts, review timing/status visibility, and safer project-local autopilot state.
- **Deliberation Journal** stores every protocol run under `~/.agentcouncil/journal/` with transcript, artifact, provenance, and status metadata.
- **`/review --loop` convergence mode** tracks findings across iterations until they are verified, reopened, or explicitly accepted.
- **Blind Panel brainstorms** let multiple outside agents propose in parallel before reveal with `/brainstorm backends=...`.
- **`/inspect`** lets you browse recent sessions from inside Claude Code, and the `agentcouncil` CLI exposes the same journal from the terminal.
- **Transcript provenance** records provider, model, phase, timestamps, and turn lineage on transcript turns.

## At A Glance

| Capability | What it gives you |
|:---|:---|
| `/autopilot` | Governed delivery with the active host agent doing implementation |
| Protocols | Independent proposal, review, decision, and challenge workflows |
| Convergence | Iterative review loops that track finding status across passes |
| Journal + Inspect | Persistent history and session replay for past deliberations |
| Blind Panel | Multiple independent outside proposals before synthesis |
| Autopilot MCP Tools | Run state, tiering, status, and resume infrastructure under the skill |

## Core Skills

Claude Code, Codex, or Cursor orchestrates these skills as the host agent. The outside agent is a separate LLM session.

| You're asking... | Command | What happens |
|:---|:---|:---|
| "Build this with council gates" | `/autopilot` | Writes a spec, reviews it, plans, builds, verifies, and keeps council gates in the loop |
| "What should we do?" | `/brainstorm` | Both agents propose independently, then negotiate toward consensus |
| "Is this good?" | `/review` | The host agent frames the question, outside agent reviews independently |
| "Review iteratively" | `/review --loop` | Iterative review: findings → describe fix → re-review → verify |
| "Which one?" | `/decide` | The host agent defines options, outside agent evaluates each one |
| "Will this break?" | `/challenge` | Outside agent attacks assumptions, the host agent defends |
| "What happened?" | `/inspect` | View past deliberation sessions from the journal |

> **Release headline:** start with `/autopilot` when you want AgentCouncil to drive delivery, and use the other skills when you want focused deliberation.

## Autopilot

AgentCouncil now includes an **`/autopilot` skill** for Claude Code and Codex. It is the primary user-facing workflow for autonomous delivery with council review built in.

**What `/autopilot` does:**

- reads your request and local project conventions
- writes a persisted spec under `docs/autopilot/specs/`
- reviews the spec before planning
- produces and reviews an implementation plan
- builds the change, gathers evidence, and reviews the build
- verifies acceptance criteria before shipping

The skill is designed to keep the active host agent doing the implementation work while AgentCouncil's review and challenge tools provide stage gates.

Choose the review/challenge model with backend profiles:

```text
/autopilot backend=openrouter-gpt challenge_backend=bedrock-sonnet Add audit logging
```

`backend` is used for all `review_loop` gates. `challenge_backend` is used for the conditional adversarial challenge gate and defaults to `backend` when omitted. The spec, plan, build, verify, and ship work runs on the active host model.

For `0.3.x`, review speed is opt-in so existing Opus-based review behavior remains compatible:

```text
/autopilot review_depth=balanced lead_review_model=sonnet Add audit logging
```

`review_depth=legacy` preserves the current behavior. `fast` and `balanced` run the independent outside reviewer and internal lead-review subprocess in parallel, return a single consolidated pass, and leave actual revisions to the lead agent before a re-review. `deep` keeps the longer iterative convergence behavior. `lead_review_model` applies only to that internal review subprocess, not to the host session doing the implementation.

### `/autopilot` flow

```
spec_prep → review_loop → plan → review_loop → build → review_loop → verify → challenge? → ship
```

### Autopilot infrastructure

Under the hood, AgentCouncil also includes a typed MCP autopilot pipeline with durable run state:

Each stage produces a typed artifact (SpecPrepArtifact, PlanArtifact, etc.). Stages with gates (`spec_prep`, `plan`, and `build` use review_loop; `verify` uses challenge conditionally) must pass before advancing. Gates can advance, request revision, or block for human approval. During long gates, `autopilot_status` exposes `review_state` with backend, lead model, budget, elapsed timing, and reviewer provenance.

### MCP Tools

| Tool | Purpose |
|------|---------|
| `autopilot_prepare` | Validate spec, classify tier, create run |
| `autopilot_context_pack` | Build or reuse a sanitized review context pack for faster gates |
| `autopilot_checkpoint` | Record durable skill-path protocol progress and next required gate |
| `autopilot_start` | Execute the full pipeline |
| `autopilot_status` | Inspect current run state |
| `autopilot_resume` | Continue a paused run |

### Three-Tier Autonomy

Runs are classified into tiers based on target files:
- **Tier 1** — Low-risk changes
- **Tier 2** — Standard changes (default)
- **Tier 3** — Sensitive paths (`auth/`, `migrations/`, `infra/`, `deploy/`, `permissions/`) — triggers challenge gate after verify

Tier only promotes (never demotes). Sensitive file detection during execution can promote mid-run.

### Current Status

- **Use `/autopilot` as the main host-agent experience.** It is the best way to exercise the workflow end to end today.
- **The typed MCP autopilot tools are available now** for run creation, checkpointing, persistence, tier classification, status, and resume.
- **The MCP autopilot path is still evolving.** Its gate execution and some runner behavior remain more infrastructure-oriented than the higher-level `/autopilot` skill experience.

## Quick Start

### Prerequisites

1. Claude Code, Codex, or Cursor — the host environment
2. macOS or Linux (Windows support planned for a future release)

That's all you need. **The default outside agent backend is the host you run on** — Claude Code → Claude, Codex → Codex, Cursor → Cursor — so deliberations work out of the box on every host with zero configuration. Set `backend=` (or a `default_profile`) to point the outside agent at a different model family for more cognitive diversity. Running on Cursor? See [CURSOR.md](docs/CURSOR.md).

<details>
<summary><strong>Optional: additional backends</strong></summary>

For cross-backend cognitive diversity (different model families = more diverse proposals), install an alternative backend:

```bash
# Codex (GPT family — maximum diversity)
npm install -g @openai/codex

# Or use Ollama for fully local deliberations
pip install "agentcouncil[ollama]"
ollama pull llama3.1:8b
```

See [BACKENDS.md](docs/BACKENDS.md) for all supported backends including Cursor, OpenRouter, Bedrock, and Kiro, and [CURSOR.md](docs/CURSOR.md) for running on Cursor.

</details>

### Install In Claude Code

Add the plugin from the marketplace, then install it:

```
/plugin marketplace add kiran-agentic/agentcouncil
/plugin install agentcouncil@agentcouncil
```

<details>
<summary><strong>Alternative: manual install from source</strong></summary>

If you prefer to install from source instead of the plugin marketplace:

```bash
git clone https://github.com/kiran-agentic/agentcouncil.git
cd agentcouncil
```

Then register the MCP server in your Claude Code project settings (`.claude/settings.json`). If you have `uv` installed (recommended, handles dependencies automatically):

```json
{
  "mcpServers": {
    "agentcouncil": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/agentcouncil", "python", "-m", "agentcouncil.server"]
    }
  }
}
```

Or with a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

```json
{
  "mcpServers": {
    "agentcouncil": {
      "command": "/path/to/agentcouncil/.venv/bin/python3",
      "args": ["-m", "agentcouncil.server"]
    }
  }
}
```

And copy the skill files so Claude Code can find them:

```bash
cp -r skills/ .claude/skills/
```

</details>

### Install In Codex

AgentCouncil now includes Codex plugin metadata:

- `.codex-plugin/plugin.json` declares the Codex plugin, shared skills, and interface metadata.
- `.mcp.json` starts the local AgentCouncil MCP server through `scripts/start-server.sh`.
- `scripts/start-server.sh` understands both Codex and Claude plugin environment variables.

When installed as a Codex plugin, Codex loads the same `skills/` workflows and acts as the host lead. Use `backend=claude` for a native Claude outside reviewer, `backend=codex` for a separate fresh Codex outside session, or named profiles from `.agentcouncil.json`.

### Upgrade

**Plugin install (marketplace):**

Refresh the marketplace listing, update the installed plugin, then reload plugins:

```
/plugin marketplace update agentcouncil
/plugin update agentcouncil@agentcouncil
/reload-plugins
```

For a user-scope install from the terminal:

```bash
claude plugin marketplace update agentcouncil
claude plugin update agentcouncil@agentcouncil --scope user
```

If Claude Code says AgentCouncil is already current but you expected a newer release, confirm the release bumped `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`. Claude Code uses plugin version metadata when deciding what is new.

**Fallback: clean reinstall**

Use this when skills do not appear, MCP tools look stale, or the marketplace install does not refresh the cached plugin:

```
/plugin uninstall agentcouncil@agentcouncil
/plugin marketplace update agentcouncil
/plugin install agentcouncil@agentcouncil
/reload-plugins
```

For a user-scope reinstall from the terminal:

```bash
claude plugin uninstall agentcouncil@agentcouncil --scope user
claude plugin marketplace update agentcouncil
claude plugin install agentcouncil@agentcouncil --scope user
```

If Claude Code still loads an old cached copy, clear the AgentCouncil plugin cache and reinstall:

```bash
rm -rf ~/.claude/plugins/cache/agentcouncil
claude plugin install agentcouncil@agentcouncil --scope user
```

Restart Claude Code or run `/reload-plugins` after reinstalling.

**Manual install (from source):**

```bash
git pull
pip install -e .
```

If you installed skills manually (`cp -r skills/ .claude/skills/`), re-copy them to pick up new or updated skills:

```bash
cp -r skills/ .claude/skills/
```

No configuration changes or migrations are required between versions. New features, including `/autopilot`, journal, convergence loops, and inspector, activate automatically. See [CHANGELOG.md](CHANGELOG.md) for what's new in each version.

### Use

```
/brainstorm How should we handle caching for our API?
```

That's it. Claude Code writes its proposal, sends a neutral brief to the outside agent, the outside agent proposes independently, they negotiate, and you get a structured consensus.

Want more depth? Add rounds, use multiple backends, run iterative review, or use autopilot:

```
/brainstorm 4 rounds How should we handle caching for our API?
/review --loop Review this code until all findings are fixed
/brainstorm backends=codex,ollama-local How should we cache?   # Blind Panel: 2 independent proposals
/autopilot Add a smoke test for the inspector CLI help output
```

### What To Use When

| Goal | Command |
|:---|:---|
| Explore solutions independently | `/brainstorm` |
| Compare concrete options | `/decide` |
| Get an independent critique | `/review` |
| Fix until findings are verified | `/review --loop` |
| Stress-test a plan before shipping | `/challenge` |
| Run a governed implementation workflow | `/autopilot` |
| Inspect past sessions | `/inspect` |

### Inspect Past Deliberations

Every protocol run is persisted to a local journal. Use `/inspect` inside Claude Code or the CLI:

```
/inspect recent                                # List recent sessions
/inspect <session_id>                          # View a specific session
```

From the terminal (after `pip install`):

```bash
agentcouncil --list                            # List recent sessions
agentcouncil <session_id>                      # View formatted transcript
agentcouncil <session_id> --json               # Raw JSON output
```

## How It Works

Each protocol gives Claude Code and the outside agent **distinct roles**:

```
/brainstorm                                /review
┌───────────────────────────────────┐      ┌───────────────────────────────────┐
│ Claude proposes (full context)    │      │ Claude frames (files + question)  │
│ Outside proposes (neutral brief)  │      │ Outside reviews (fresh eyes)      │
│ They negotiate → consensus        │      │ Claude responds (codebase knowledge)│
└───────────────────────────────────┘      └───────────────────────────────────┘

/decide                                    /challenge
┌───────────────────────────────────┐      ┌───────────────────────────────────┐
│ Claude defines (options + criteria)│      │ Outside attacks (assumptions)     │
│ Outside evaluates (each option)   │      │ Claude defends (with evidence)    │
│ Structured comparison → winner    │      │ Attack/defense → readiness        │
└───────────────────────────────────┘      └───────────────────────────────────┘
```

Only **brainstorm** has bilateral independence (both propose blind). The other three give Claude Code a specific role — framer, definer, or defender — so the outside agent's independent evaluation is the focus.

<details>
<summary><strong>Choosing the outside agent</strong></summary>

AgentCouncil supports multiple backends via named profiles. By default, a fresh Claude session is the outside agent — it works out of the box inside Claude Code with no setup. For maximum cognitive diversity, configure a different model family (Codex, Ollama, OpenRouter, Bedrock, or Kiro).

### Three ways to select a backend

**a. Per-invocation (skill argument)**

```
/brainstorm backend=local-llama How should we handle caching?
```

**b. Profile config**

Create `.agentcouncil.json` in your project root (or `~/.agentcouncil.json` for global defaults). See [BACKENDS.md](docs/BACKENDS.md) for full profile config reference.

**c. Legacy env var**

```bash
export AGENTCOUNCIL_OUTSIDE_AGENT=claude
```

Still supported for backward compatibility.

### Backend comparison

| Backend | Install | Independence |
|---------|---------|-------------|
| claude (default) | Already available in Claude Code | Same-backend |
| codex | `codex` CLI on PATH | Cross-backend (GPT family) |
| ollama | `pip install "agentcouncil[ollama]"` | Varies by model |
| openrouter | `pip install "agentcouncil[openrouter]"` | Varies by model |
| bedrock | `pip install "agentcouncil[bedrock]"` | Cross-backend |
| kiro | `kiro-cli` on PATH | Cross-backend |

See [docs/BACKENDS.md](docs/BACKENDS.md) for full setup instructions, independence tiers, and workspace access details.

</details>

<details>
<summary><strong>Development setup</strong></summary>

For contributing or running the Python library/MCP server:

```bash
git clone https://github.com/kiran-agentic/agentcouncil.git
cd agentcouncil
pip install -e ".[dev]"
pytest
```

Python 3.12+ required. Tests use `StubProvider` — no CLI tools needed. To include specific backends for testing:

```bash
pip install -e ".[dev,ollama]"
```

Integration tests require `claude` and `codex` CLIs on PATH:

```bash
pytest -m real
```

**Note for plugin developers:** If you installed AgentCouncil via the plugin marketplace and are also editing the source, the plugin cache won't auto-sync with your changes. For skill-only changes, copying `skills/` is enough. For full workflow or server changes, sync the cached plugin copy:

```bash
PLUGIN=~/.claude/plugins/cache/agentcouncil/agentcouncil/0.6.1

rsync -a --delete agentcouncil/ "$PLUGIN/agentcouncil/"
rsync -a --delete skills/ "$PLUGIN/skills/"
rsync -a --delete scripts/ "$PLUGIN/scripts/"
rsync -a --delete .claude-plugin/ "$PLUGIN/.claude-plugin/"
cp pyproject.toml "$PLUGIN/pyproject.toml"
```

Then run `/reload-plugins` in Claude Code. Users who install via `/plugin update agentcouncil@agentcouncil` get fresh cache automatically.

</details>

## Documentation

| Doc | What it covers |
|:----|:---------------|
| [PROTOCOLS.md](docs/PROTOCOLS.md) | Side-by-side protocol comparison with worked example |
| [BACKENDS.md](docs/BACKENDS.md) | Backend selection and independence tiers |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical design for contributors |
| [CHANGELOG.md](CHANGELOG.md) | Release-by-release feature history and limitations |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | How to contribute |

## License

[Apache 2.0](LICENSE)
