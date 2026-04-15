<div align="center">

# AgentCouncil

**Multi-agent deliberation protocols for AI coding assistants.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](LICENSE)
[![Tests](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml/badge.svg)](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml)

Two agents. Distinct roles. No echo chamber.

AgentCouncil convenes Claude Code and an outside agent — each with a distinct role — to deliberate on problems. In brainstorm, both propose independently before seeing each other's work. In review, decide, and challenge, the outside agent evaluates, compares, or attacks without seeing Claude Code's internal reasoning. The outside agent defaults to a fresh Claude session, or you can configure Codex, Ollama, OpenRouter, Bedrock, or Kiro for cross-model diversity.

**v2.0 infrastructure:** Persistent deliberation journal, iterative convergence loops (review findings that loop until verified), sealed N-party Blind Panel proposals, resumable protocol state, a CLI session inspector, and an autopilot pipeline with typed artifacts, durable run state, gate normalization, and tier classification. Expert Witness specialist checks and live Turn Stream events are available as building blocks but not yet wired into protocol execution.

</div>

---

## Four Protocols

Claude Code (referred to as "Claude" in protocol descriptions below) orchestrates all four protocols. The outside agent is a separate LLM session.

| You're asking... | Command | What happens |
|:---|:---|:---|
| "What should we do?" | `/brainstorm` | Both agents propose independently, then negotiate toward consensus |
| "Is this good?" | `/review` | Claude Code frames the question, outside agent reviews independently |
| "Review iteratively" | `/review --loop` | Iterative review: findings → describe fix → re-review → verify |
| "Which one?" | `/decide` | Claude Code defines options, outside agent evaluates each one |
| "Will this break?" | `/challenge` | Outside agent attacks assumptions, Claude Code defends |
| "What happened?" | `/inspect` | View past deliberation sessions from the journal |

> **Common flow:** brainstorm (explore) → decide (choose) → review (check) → challenge (stress-test)

## Autopilot Pipeline

v2.0 adds a gated work pipeline that sequences five stages with typed artifacts, persistent state, and tiered autonomy:

```
spec_prep → plan → build → verify → ship
```

Each stage produces a typed artifact (SpecPrepArtifact, PlanArtifact, etc.). Stages with gates (`plan` and `build` use review_loop; `verify` uses challenge conditionally) must pass before advancing. Gates can advance, request revision, or block for human approval. `spec_prep` and `ship` have no gates.

### MCP Tools

| Tool | Purpose |
|------|---------|
| `autopilot_prepare` | Validate spec, classify tier, create run |
| `autopilot_start` | Execute the full pipeline |
| `autopilot_status` | Inspect current run state |
| `autopilot_resume` | Continue a paused run |

### Three-Tier Autonomy

Runs are classified into tiers based on target files:
- **Tier 1** — Low-risk changes
- **Tier 2** — Standard changes (default)
- **Tier 3** — Sensitive paths (`auth/`, `migrations/`, `infra/`, `deploy/`, `permissions/`) — triggers challenge gate after verify

Tier only promotes (never demotes). Sensitive file detection during execution can promote mid-run.

### Current Limitations

- `plan` and `build` stages use stub runners — real implementations planned
- Gates use stub protocol artifacts, not live backend deliberation sessions
- No skill/slash-command interface yet — autopilot is MCP-tool only

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

```
/plugin update agentcouncil
/reload-plugins
```

**Manual install (from source):**

```bash
git pull
pip install -e .
```

If you installed skills manually (`cp -r skills/ .claude/skills/`), re-copy them to pick up new or updated skills:

```bash
cp -r skills/ .claude/skills/
```

No configuration changes or migrations are required between versions. New features (journal, convergence loops, inspector) activate automatically. See [CHANGELOG.md](CHANGELOG.md) for what's new in each version.

### Use

```
/brainstorm How should we handle caching for our API?
```

That's it. Claude Code writes its proposal, sends a neutral brief to the outside agent, the outside agent proposes independently, they negotiate, and you get a structured consensus.

Want more depth? Add rounds, use multiple backends, or run iterative review:

```
/brainstorm 4 rounds How should we handle caching for our API?
/review --loop Review this code until all findings are fixed
/brainstorm backends=codex,ollama-local How should we cache?   # Blind Panel: 2 independent proposals
```

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

**Note for plugin developers:** If you installed AgentCouncil via the plugin marketplace and are also editing the source, the plugin cache won't auto-sync with your changes. After modifying or adding skill files, copy them to the cache:

```bash
cp -r skills/ ~/.claude/plugins/cache/agentcouncil/agentcouncil/*/skills/
```

Then run `/reload-plugins` in Claude Code. Users who install via `/plugin update` get fresh cache automatically.

</details>

## Documentation

| Doc | What it covers |
|:----|:---------------|
| [PROTOCOLS.md](docs/PROTOCOLS.md) | Side-by-side protocol comparison with worked example |
| [BACKENDS.md](docs/BACKENDS.md) | Backend selection and independence tiers |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical design for contributors |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | How to contribute |

## License

[Apache 2.0](LICENSE)
