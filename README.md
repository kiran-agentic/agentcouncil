<div align="center">

# AgentCouncil

**Multi-agent deliberation protocols for AI coding assistants.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](LICENSE)
[![Tests](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml/badge.svg)](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml)

The biggest release in `0.3.0`: **`/autopilot`**.

AgentCouncil now ships a council-governed autonomous delivery workflow for Claude Code. You start with **`/autopilot`**, AgentCouncil writes and reviews the spec, plans the work, builds it, re-reviews the build, verifies the result, and only then moves toward shipping.

Underneath that headline feature, AgentCouncil still provides its core multi-agent protocols: `/brainstorm`, `/review`, `/decide`, `/challenge`, and `/inspect`. Claude Code works with an outside agent that stays independent by role, backend, and session. The outside agent defaults to a fresh Claude session, or you can configure Codex, Ollama, OpenRouter, Bedrock, or Kiro for cross-model diversity.

</div>

---

## What's New In 0.3.x

The `0.3.x` series is centered on **`/autopilot`**:

- **`/autopilot`** is now the headline workflow: a governed implementation skill for Claude Code with spec, planning, build, review, verification, and ship stages.
- **`0.3.1` patch:** adds opt-in faster review gates with `review_depth=fast|balanced`, sanitized `ReviewContextPack` artifacts, review timing/status visibility, and safer project-local autopilot state.
- **Deliberation Journal** stores every protocol run under `~/.agentcouncil/journal/` with transcript, artifact, provenance, and status metadata.
- **`/review --loop` convergence mode** tracks findings across iterations until they are verified, reopened, or explicitly accepted.
- **Blind Panel brainstorms** let multiple outside agents propose in parallel before reveal with `/brainstorm backends=...`.
- **`/inspect`** lets you browse recent sessions from inside Claude Code, and the `agentcouncil` CLI exposes the same journal from the terminal.
- **Transcript provenance** records provider, model, phase, timestamps, and turn lineage on transcript turns.

## At A Glance

| Capability | What it gives you |
|:---|:---|
| `/autopilot` | The main governed delivery skill for Claude Code |
| Protocols | Independent proposal, review, decision, and challenge workflows |
| Convergence | Iterative review loops that track finding status across passes |
| Journal + Inspect | Persistent history and session replay for past deliberations |
| Blind Panel | Multiple independent outside proposals before synthesis |
| Autopilot MCP Tools | Run state, tiering, status, and resume infrastructure under the skill |

## Core Skills

Claude Code (referred to as "Claude" in protocol descriptions below) orchestrates these skills. The outside agent is a separate LLM session.

| You're asking... | Command | What happens |
|:---|:---|:---|
| "Build this with council gates" | `/autopilot` | Writes a spec, reviews it, plans, builds, verifies, and keeps council gates in the loop |
| "What should we do?" | `/brainstorm` | Both agents propose independently, then negotiate toward consensus |
| "Is this good?" | `/review` | Claude Code frames the question, outside agent reviews independently |
| "Review iteratively" | `/review --loop` | Iterative review: findings → describe fix → re-review → verify |
| "Which one?" | `/decide` | Claude Code defines options, outside agent evaluates each one |
| "Will this break?" | `/challenge` | Outside agent attacks assumptions, Claude Code defends |
| "What happened?" | `/inspect` | View past deliberation sessions from the journal |

> **Release headline:** start with `/autopilot` when you want AgentCouncil to drive delivery, and use the other skills when you want focused deliberation.

## Autopilot

AgentCouncil now includes an **`/autopilot` skill** for Claude Code. It is the primary user-facing workflow for autonomous delivery with council review built in.

**What `/autopilot` does:**

- reads your request and local project conventions
- writes a persisted spec under `docs/autopilot/specs/`
- reviews the spec before planning
- produces and reviews an implementation plan
- builds the change, gathers evidence, and reviews the build
- verifies acceptance criteria before shipping

The skill is designed to keep Claude doing the implementation work while AgentCouncil's review and challenge tools provide stage gates.

Choose the review/challenge model with backend profiles:

```text
/autopilot backend=openrouter-gpt challenge_backend=bedrock-sonnet Add audit logging
```

`backend` is used for all `review_loop` gates. `challenge_backend` is used for the conditional adversarial challenge gate and defaults to `backend` when omitted. The spec, plan, build, verify, and ship work runs on the active Claude Code lead model.

For `0.3.x`, review speed is opt-in so existing Opus-based review behavior remains compatible:

```text
/autopilot review_depth=balanced lead_review_model=sonnet Add audit logging
```

`review_depth=legacy` preserves the current behavior. `fast` and `balanced` run the independent outside reviewer and internal lead-review subprocess in parallel, return a single consolidated pass, and leave actual revisions to the lead agent before a re-review. `deep` keeps the longer iterative convergence behavior. `lead_review_model` applies only to that internal review subprocess, not to the Claude Code session doing the implementation.

### `/autopilot` flow

```
spec_prep → review_loop → plan → review_loop → build → review_loop → verify → challenge? → ship
```

### Autopilot infrastructure

Under the hood, `0.3.0` also adds a typed MCP autopilot pipeline with durable run state:

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

- **Use `/autopilot` as the main Claude Code experience.** It is the best way to exercise the workflow end to end today.
- **The typed MCP autopilot tools are available now** for run creation, checkpointing, persistence, tier classification, status, and resume.
- **The MCP autopilot path is still evolving.** Its gate execution and some runner behavior remain more infrastructure-oriented than the higher-level `/autopilot` skill experience.

## Quick Start

### Prerequisites

1. [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — the host environment
2. macOS or Linux (Windows support planned for a future release)

That's all you need. Claude is the default outside agent backend — it's already available inside Claude Code with zero configuration.

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

See [BACKENDS.md](docs/BACKENDS.md) for all supported backends including OpenRouter, Bedrock, and Kiro.

</details>

### Install

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
PLUGIN=~/.claude/plugins/cache/agentcouncil/agentcouncil/0.3.0

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
