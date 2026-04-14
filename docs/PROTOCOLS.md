# Protocols

AgentCouncil provides four deliberation protocols plus v2.0 infrastructure for iterative workflows, multi-agent panels, and specialist consultation. Each protocol convenes Claude Code (the orchestrator, referred to as "Claude" below) and an outside agent — with different roles depending on the protocol. The outside agent can be Codex, a fresh Claude session, or any configured backend (Ollama, OpenRouter, Bedrock, Kiro, or other providers).

## Quick Chooser

| You're asking... | Use |
|-----------------|-----|
| "What should we do?" | **brainstorm** |
| "Is this good?" | **review** |
| "Which one?" | **decide** |
| "Will this break?" | **challenge** |
| "Fix until clean" | **review** (convergence loop via `review_loop` tool) |
| "Get N perspectives" | **brainstorm** with `backends=` (Blind Panel) |

## Protocol Comparison

| | Brainstorm | Review | Decide | Challenge |
|---|-----------|--------|--------|-----------|
| **Purpose** | Generate and converge on solutions | Get independent critique | Compare options | Stress-test before shipping |
| **Claude Code's role** | Proposes independently | Frames question, responds to findings | Defines decision space, adds context | Defends the plan |
| **Outside agent's role** | Proposes independently | Reviews with fresh eyes | Evaluates options | Attacks assumptions |
| **Independence** | Bilateral -- both propose blind | One-directional -- outside reviews blind | One-directional -- outside evaluates blind | Adversarial -- outside attacks, Claude defends |
| **Default rounds** | 1 | 1 | 1 | 2 |
| **Output** | Consensus direction | Severity-rated findings with verdict | Option assessments with winner | Failure modes with readiness verdict |
| **Invocation** | `/brainstorm` | `/review` | `/decide` | `/challenge` |

> **Backend selection:** All protocols accept an optional `backend=` parameter to select the outside agent backend. For example: `/brainstorm backend=ollama-llama3 How should we handle caching?`. The backend can be a named profile from `.agentcouncil.json` (e.g. `backend=my-ollama-profile`) or a legacy string (`backend=codex`, `backend=claude`). Defaults to the `AGENTCOUNCIL_OUTSIDE_AGENT` env var, then `claude`.

> **Exchange rounds:** You can control how many rounds of back and forth the agents have by adding a round count to your command. For example: `/brainstorm 4 rounds How should we handle caching?`. More rounds give the agents more time to negotiate and refine their positions. Brainstorm, review, and decide default to 1 round. Challenge defaults to 2 rounds because attack/defense benefits from deeper exchange.

## How Each Protocol Works

### Brainstorm

Both agents form independent positions before seeing each other's work.

```
[1] Claude writes its proposal (full conversation context)
         ┌─────────────────────────────────────┐
         │ Outside agent has NOT seen anything  │
         └─────────────────────────────────────┘
[2] Claude sends neutral brief ────► Outside proposes independently
[3] Claude shares its proposal ────► Outside compares, pushes back
[4] Exchange rounds (if disagreements)
[5] Outside synthesizes ──────────► ConsensusArtifact JSON
```

**When to use:** You don't know the answer yet. You want genuinely independent ideas before converging.

### Review

Claude frames the review question. The outside agent reviews independently.

```
[1] Claude gathers context — what to review, what files, what question
[2] Claude sends directed review request ────► Outside reviews independently
     (file paths, focus areas, concerns)        (findings with severity + evidence)
[3] Claude responds to findings with codebase knowledge
     (confirms, disputes with evidence, adds context)
[4] Outside synthesizes ────────────────────► ReviewArtifact JSON
```

**When to use:** Work is done. You want independent critique from fresh eyes. Claude is the builder responding to feedback, not a second reviewer.

### Decide

Claude defines the decision space. The outside agent evaluates the options.

```
[1] Claude identifies decision, options, criteria, constraints
[2] Claude sends evaluation request ────► Outside evaluates each option
     (options + file paths for context)    (pros, cons, risks, confidence per option)
[3] Claude responds with codebase context
     (corrects assumptions, adds evidence)
[4] Outside synthesizes ───────────────► DecideArtifact JSON
```

**When to use:** You have 2+ options and need to pick one. The outside agent can only evaluate provided options -- it cannot invent new ones.

### Challenge

Claude sends the plan. The outside agent attacks it. Claude defends.

```
[1] Claude identifies target, assumptions, success criteria
[2] Claude sends attack brief ──────► Outside attacks assumptions
     (plan + assumptions + file paths)  (failure modes, break conditions)
[3] Claude DEFENDS against attacks with evidence
[4] Outside attacks the defense (default: 1 more round)
[5] Claude counter-defends
[6] Outside synthesizes ──────────► ChallengeArtifact JSON
```

**When to use:** You have a plan you're about to commit to. You want it stress-tested. The outside agent finds failure modes but does NOT propose fixes.

## Worked Example: API Caching

Same scenario, four protocols:

**Scenario:** Python API aggregating third-party SaaS data. Bursty traffic, rate-limited upstream, user-scoped responses. Dashboard reads tolerate 60s staleness; writes and auth cannot.

### Through brainstorm

"We need a caching strategy. What should we do?"

Both agents independently propose approaches. Claude suggests Redis + in-process LRU. Outside suggests Redis-only. They negotiate. Output: recommended direction with agreement/disagreement points.

### Through review

"Review our Redis caching implementation for gaps."

Claude tells outside: "Read cache.py and server.py. Check for: invalidation completeness, TTL correctness for user-scoped keys, error handling on Redis failure. Key concern: write-through invalidation may miss the batch import endpoint."

Outside reviews the actual code and returns findings.

### Through decide

"Should we use Redis, in-process LRU, or no cache?"

Claude defines three options with descriptions. Outside evaluates each for pros, cons, blocking risks. Output: winner with tradeoff analysis.

### Through challenge

"Stress-test our caching plan before we ship."

Claude states assumptions: Redis always available, 60s staleness acceptable, write-through catches all mutations. Outside attacks each assumption. Claude defends. Output: readiness verdict with surviving/broken assumptions.

## v2.0 Protocol Extensions

### Convergence Loops (Iterative Review)

One-shot review finds issues but doesn't verify they're fixed. Convergence loops close that gap:

```
[1] Initial review → produces findings with severities
[2] Lead addresses findings → describes what was changed
[3] Scoped re-review → checks prior findings + regressions (not full re-review)
[4] Loop until: all verified, max iterations, or explicit approval
```

**Per-finding status tracking:** `open` → `fixed` → `verified` (or `reopened`, `wont_fix`).

Currently available for review only. Challenge and decide convergence patterns will follow.

### Blind Panel (N-Party Brainstorm)

Standard brainstorm uses one outside agent. Blind Panel uses multiple:

```
[1] Claude writes proposal (full context)
[2] N outside agents each receive the same brief
[3] Each proposes independently (sealed — no agent sees another's proposal)
[4] All proposals revealed simultaneously
[5] Structured synthesis across N+1 proposals
```

Invoke with: `/brainstorm backends=codex,ollama-local How should we handle caching?`

Maximum 5 outside agents. Partial panel on failure (continues with remaining agents).

### Expert Witness (Specialist Checks)

When a deliberation surfaces a sub-question neither agent can evaluate well, a specialist agent can be consulted:

- Receives only the targeted sub-question + minimal context (never the full debate)
- Returns typed evaluative output aligned to the parent protocol
- Evidence is advisory — must be cited in synthesis if used, but is not binding
- One check per protocol run by default

## Choosing the Right Protocol

A common flow: **brainstorm** (explore approaches) -> **decide** (choose one) -> **review** (check the implementation) -> **challenge** (stress-test before shipping).

But each works standalone:
- Got a vague problem? **brainstorm**
- Got something to check? **review**
- Got options to compare? **decide**
- Got a plan to ship? **challenge**
- Want iterative review? Use `review_loop` MCP tool
- Want N perspectives? Use `backends=` with brainstorm
