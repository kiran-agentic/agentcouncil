<div align="center">

# AgentCouncil

**Multi-agent deliberation protocols for AI coding assistants.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=for-the-badge)](LICENSE)
[![Tests](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml/badge.svg)](https://github.com/kiran-agentic/agentcouncil/actions/workflows/tests.yml)

Two agents. Distinct roles. No echo chamber.

AgentCouncil convenes Claude Code and an outside agent — each with a distinct role — to deliberate on problems. In brainstorm, both propose independently before seeing each other's work. In review, decide, and challenge, the outside agent evaluates, compares, or attacks without seeing Claude Code's internal reasoning. The outside agent defaults to a fresh Claude session, or you can configure Codex, Ollama, OpenRouter, Bedrock, or Kiro for cross-model diversity.

</div>

---

## Four Protocols

Claude Code (referred to as "Claude" in protocol descriptions below) orchestrates all four protocols. The outside agent is a separate LLM session.

| You're asking... | Command | What happens |
|:---|:---|:---|
| "What should we do?" | `/brainstorm` | Both agents propose independently, then negotiate toward consensus |
| "Is this good?" | `/review` | Claude Code frames the question, outside agent reviews independently |
| "Which one?" | `/decide` | Claude Code defines options, outside agent evaluates each one |
| "Will this break?" | `/challenge` | Outside agent attacks assumptions, Claude Code defends |

> **Common flow:** brainstorm (explore) → decide (choose) → review (check) → challenge (stress-test)

## Quick Start

### Prerequisites

1. [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — the host environment

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

### Use

```
/brainstorm How should we handle caching for our API?
```

That's it. Claude Code writes its proposal, sends a neutral brief to the outside agent, the outside agent proposes independently, they negotiate, and you get a structured consensus.

Want more depth? Add rounds for additional exchange:

```
/brainstorm 4 rounds How should we handle caching for our API?
/challenge 3 rounds Stress test our deployment plan
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
