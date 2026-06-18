# Running AgentCouncil on Cursor

AgentCouncil runs on [Cursor](https://cursor.com) the same way it runs in Claude
Code and Codex: Cursor's agent is the **host** (orchestrator + lead), and an
independent **outside agent** provides a second, separate perspective during a
deliberation. On Cursor:

- the **default backend is Cursor itself** — no external CLI required, because
  "the backend it runs on" is the zero-config default (see
  [Host-Aware Default](#host-aware-default));
- deliberations can use **different Cursor models** — e.g. pit `gpt-5` against
  `sonnet-4.5` — independently of whichever model you have selected in the editor.

Everything is delivered through two Cursor-native mechanisms: an **MCP server**
(`.cursor/mcp.json`) and **slash commands** (`.cursor/commands/*.md`).

---

## Prerequisites

1. **Cursor** with the **`cursor-agent` CLI** installed and authenticated. The CLI
   is what AgentCouncil shells out to for the outside agent.
   ```bash
   # install the Cursor CLI — see https://cursor.com/docs/cli
   cursor-agent login        # or export CURSOR_API_KEY=...
   cursor-agent --list-models  # confirm which models your account can use
   ```
2. **Python 3.12+** and (recommended) [`uv`](https://docs.astral.sh/uv/). The MCP
   server bootstraps itself via `scripts/start-server.sh` (uv first, venv+pip
   fallback).

> The `cursor-agent` CLI is only required for the **outside agent**. The host/lead
> is Cursor's own in-editor agent, which needs no extra setup.

---

## Install

AgentCouncil ships a ready-to-use `.cursor/` directory in this repository. Use it
directly (when working inside the AgentCouncil repo) or copy it into your own
project.

### 1. Register the MCP server

Copy [`.cursor/mcp.json`](../.cursor/mcp.json) into your project (merge it if you
already have one), or add it to `~/.cursor/mcp.json` for all projects:

```json
{
  "mcpServers": {
    "agentcouncil": {
      "command": "/absolute/path/to/agentcouncil/scripts/start-server.sh",
      "args": [],
      "env": { "AGENTCOUNCIL_HOST": "cursor" }
    }
  }
}
```

- Use an **absolute path** to `start-server.sh` when the config lives outside the
  AgentCouncil checkout. Inside this repo the relative `./scripts/start-server.sh`
  works as-is.
- **`"env": { "AGENTCOUNCIL_HOST": "cursor" }` is the important part.** Cursor does
  not expose a reliable "I am Cursor" environment marker the way Claude Code and
  Codex do, so this line is how AgentCouncil knows the host is Cursor (and therefore
  that the default backend should be Cursor). Without it, the default backend falls
  back to `claude`.

Restart Cursor (or toggle the MCP server) so it picks up the config.

### 2. Install the slash commands

Copy the generated commands into your project's `.cursor/commands/` (or
`~/.cursor/commands/` for global availability):

```bash
cp agentcouncil/.cursor/commands/*.md  your-project/.cursor/commands/
```

These are generated from the canonical `skills/*/SKILL.md` (the same protocols
Claude Code and Codex use), so they never drift. Regenerate them after editing a
skill:

```bash
python scripts/generate-cursor-commands.py
```

You now have `/brainstorm`, `/challenge`, `/decide`, `/review`, `/inspect`, and
`/autopilot` in Cursor's chat.

---

## Host-Aware Default

The **default backend is the host AgentCouncil runs under** — "the backend it runs
on":

| Host        | Default outside backend | Default lead |
|-------------|-------------------------|--------------|
| Claude Code | `claude`                | `claude`     |
| Codex       | `codex`                 | `codex`      |
| **Cursor**  | **`cursor`**            | **`cursor`** |

On Cursor that means a zero-config deliberation spawns a **fresh, independent
`cursor-agent` session** as the outside agent. This is the
*same-backend-fresh-session* independence tier (separate session, no shared
context) — see [BACKENDS.md → Independence Tiers](BACKENDS.md#independence-tiers).
For maximum cognitive diversity, point the outside agent at a **different model
family** (next section) or a different backend entirely (`backend=codex`,
`backend=claude`, …).

Resolution precedence is unchanged — explicit config always wins over the host
default:

```
backend= arg  >  default_profile (AGENTCOUNCIL_DEFAULT_PROFILE / .agentcouncil.json)
              >  AGENTCOUNCIL_OUTSIDE_AGENT (legacy)
              >  host default ("the backend it runs on")  >  "claude"
```

So if your `.agentcouncil.json` sets `default_profile`, that still takes
precedence; the host default only applies when nothing else is configured. (See the
authoritative precedence table in [BACKENDS.md](BACKENDS.md#precedence).)

---

## Using different Cursor models

The Cursor backend accepts a `model` so a single deliberation can compare two
Cursor models. Define named profiles in `.agentcouncil.json` (project root) or
`~/.agentcouncil.json` (global):

```json
{
  "profiles": {
    "cursor-gpt5":   { "provider": "cursor", "model": "gpt-5" },
    "cursor-sonnet": { "provider": "cursor", "model": "sonnet-4.5" },
    "cursor-auto":   { "provider": "cursor", "model": "auto" }
  }
}
```

Then select one per invocation:

```
/brainstorm backend=cursor-gpt5 How should we shard the write path?
/review     backend=cursor-sonnet this migration script
/decide     backend=cursor-gpt5 between optimistic and pessimistic locking
```

Run `cursor-agent --list-models` to see the model names your account supports. Pass
`"auto"` to let Cursor choose.

> The outside agent's model is independent of the model you have selected in the
> Cursor editor. You can be coding with `sonnet-4.5` while the outside agent
> deliberates with `gpt-5`.

---

## How it works under the hood

- **Outside agent** — `CursorProvider` runs `cursor-agent --print --output-format
  json` as a subprocess. It uses a **stateless "replay" session strategy**: the full
  accumulated conversation is re-sent as the prompt on every turn, so context is
  always preserved without depending on `cursor-agent`'s `--resume`. (This is a
  deliberate, conservative choice — the `--resume`/`session_id` linkage was not
  verified against a live `cursor-agent` during development; replay is always
  correct, just less token-efficient. It can be upgraded to a `--resume`-based
  persistent session once verified.) It has **native workspace access**:
  `cursor-agent` reads project files itself, so prompts reference file paths rather
  than inlining contents.
- **Lead** (library/MCP mode only) — `CursorAdapter` runs `cursor-agent --print
  --output-format text` for the lead side. In normal **skill mode** the lead is
  simply Cursor's in-editor agent running the command, so no subprocess is spawned.
- **Host detection** — `AGENTCOUNCIL_HOST=cursor` (set in `.cursor/mcp.json`) tells
  the server the host is Cursor. See [`agentcouncil/host.py`](../agentcouncil/host.py).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No module named 'rich'` / `'fastmcp'` on startup | The dependency install was incomplete (e.g. a slow first-launch install was interrupted by Cursor's MCP start timeout). `scripts/start-server.sh` self-heals: just reload the MCP server and it re-installs and verifies the deps. The **first launch** can take ~30–60s while it bootstraps; subsequent launches are instant. Installing [`uv`](https://docs.astral.sh/uv/) makes the bootstrap fast and reliable. If it persists, delete the bootstrap cache (`rm -rf <repo>/.venv-data`) and reload. |
| `cursor-agent CLI not found on PATH` | Install the [Cursor CLI](https://cursor.com/docs/cli) and ensure `cursor-agent` is on PATH (restart Cursor so the MCP server inherits the updated PATH). |
| Default backend is `claude`, not `cursor` | Confirm `.cursor/mcp.json` sets `"env": { "AGENTCOUNCIL_HOST": "cursor" }`, or set `AGENTCOUNCIL_DEFAULT_PROFILE` / `default_profile` explicitly. |
| Auth / 401 errors from `cursor-agent` | Run `cursor-agent login` or set `CURSOR_API_KEY`. |
| Slash commands don't appear | Make sure the `.md` files are in `.cursor/commands/` (project) or `~/.cursor/commands/` (global) and reload Cursor. |
| Want to verify resolution | The `show-effective-config` MCP tool reports which source provided each value. |

---

## See also

- [BACKENDS.md](BACKENDS.md) — full backend reference, precedence, independence tiers.
- [PROTOCOLS.md](PROTOCOLS.md) — what brainstorm / review / decide / challenge do.
- [ARCHITECTURE.md](ARCHITECTURE.md) — host vs. outside agent, the session API.
