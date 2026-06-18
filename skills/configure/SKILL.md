---
name: configure
description: Use when AgentCouncil's backend is unconfigured, is using the wrong or an unavailable model/agent, or you want to add or switch a backend or profile — e.g. set up Cursor models, Codex, Claude, Ollama, OpenRouter, or Bedrock, choose the default outside or lead agent, or create/repair .agentcouncil.json.
allowed-tools: mcp__agentcouncil__show-effective-config mcp__agentcouncil__get_outside_backend_info Bash Read Write Edit
argument-hint: [what to configure, e.g. "use gpt-5 via cursor" or "add openrouter as default"]
---

# AgentCouncil Configure

Set up AgentCouncil's backends: read the current configuration, detect what this
machine can actually run, and write a valid `.agentcouncil.json` — without ever
storing a secret in the file.

**Request:** $ARGUMENTS

## Core principle

AgentCouncil resolves the outside-agent backend by precedence (highest first):
explicit `backend=` argument › `default_profile` (env / `.agentcouncil.json`) ›
`AGENTCOUNCIL_OUTSIDE_AGENT` › the host it runs on (`claude` / `codex` / `cursor`) ›
`claude`. This skill edits the `default_profile` / `profiles` layer.

**API keys are NEVER written to the file.** The `api_key_env` field stores the
*name* of an environment variable; the user exports the value themselves.

## Protocol — follow these steps

### Step 1: Show the current configuration

Call `mcp__agentcouncil__show-effective-config` to see the resolved
`default_profile`, `default_lead_profile`, and `profiles` — each with the source
that provided it (`project_config`, `global_config`, `env_var`, `default`, …).

Call `mcp__agentcouncil__get_outside_backend_info` with no `profile` to see what the
**current default** resolves to: `provider`, `model`, `workspace_access`. State
plainly what is configured today and where it comes from.

### Step 2: Detect what's available

Only configure backends this environment can actually use. Detect the CLIs:

```bash
for b in cursor-agent codex claude ollama; do printf '%-12s ' "$b"; command -v "$b" || echo "(not installed)"; done
```

For API-keyed providers, check whether the env var **name** is set — never print its
value:

```bash
for v in OPENROUTER_API_KEY CURSOR_API_KEY AWS_ACCESS_KEY_ID; do printf '%-20s ' "$v"; [ -n "${!v}" ] && echo set || echo "(unset)"; done
```

### Step 3: Decide the configuration

From `$ARGUMENTS` (or by asking the user once if it is unclear), determine which
backend(s) and model(s) to set up and which should be the **default**. Prefer
backends detected as available in Step 2. If the user wants a backend whose CLI or
key is missing, tell them the single install/auth step and offer to write it anyway
(it resolves once installed).

### Backend reference

| provider | requirement | profile fields | example profile value |
|----------|-------------|----------------|-----------------------|
| `cursor` | `cursor-agent` CLI + `cursor-agent login` (or `CURSOR_API_KEY`) | `provider`, `model` | `{ "provider": "cursor", "model": "gpt-5" }` |
| `claude` | `claude` CLI on PATH | `provider`, `model` | `{ "provider": "claude", "model": "opus" }` |
| `codex` | `codex` CLI on PATH | `provider`, `model` | `{ "provider": "codex" }` |
| `ollama` | local Ollama running | `provider`, `model`, `endpoint` | `{ "provider": "ollama", "model": "llama3.1:8b" }` |
| `openrouter` | `OPENROUTER_API_KEY` exported | `provider`, `model`, `api_key_env` | `{ "provider": "openrouter", "model": "openai/gpt-4o", "api_key_env": "OPENROUTER_API_KEY" }` |
| `bedrock` | AWS credentials (boto3 chain) | `provider`, `model` | `{ "provider": "bedrock", "model": "us.anthropic.claude-3-5-sonnet-20241022-v2:0" }` |

### Step 4: Write `.agentcouncil.json`

Write to the **project root** (`./.agentcouncil.json`) by default, or
`~/.agentcouncil.json` if the user wants it global. If a file already exists, **merge**
— keep the user's other profiles.

```json
{
  "default_profile": "<name, or omit to use the host default>",
  "default_lead_profile": "<name, or omit>",
  "profiles": {
    "<name>": { "provider": "...", "model": "...", "api_key_env": "<ENV_VAR_NAME>" }
  }
}
```

Rules:
- **Never** put a raw API key, token, or password anywhere in the file. `api_key_env`
  is the env var NAME (e.g. `"OPENROUTER_API_KEY"`), not the key. If a value is
  needed, tell the user to `export <NAME>=...` in their shell — do not ask them to
  paste it into the chat.
- Omit `default_profile` entirely if the user wants the host-aware default ("the
  backend it runs on") to apply.
- Profile names are arbitrary labels (e.g. `cursor-gpt5`, `local-llama`).

### Step 5: Validate and verify

Call `mcp__agentcouncil__show-effective-config` again and confirm the new values now
resolve from `project_config` (or `global_config`). If it raises an error (for
example, a raw key in `api_key_env`), the file is invalid — fix it and re-check.

Call `mcp__agentcouncil__get_outside_backend_info` with `profile` set to the new
default and confirm its `provider` / `model`, and note its `workspace_access`.

### Step 6: Summarize

Report: what was written and where; any environment variables the user must
`export` (by name only); whether each configured backend's CLI/key is present; and
how to use it — either it is now the default, or `/brainstorm backend=<profile> …`.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Writing a raw API key into the file | Use `api_key_env` with the env var NAME. The config validator rejects raw secrets and the file will fail to load. |
| Configuring a backend whose CLI/key is missing | Detect availability first (Step 2); install/authenticate, or pick an available backend. |
| Expecting the host default to win over a set `default_profile` | An explicit `default_profile` always beats the host-aware default. Omit it to fall back to the host. |
| Overwriting the user's existing profiles | Merge into the existing `.agentcouncil.json`; preserve their other profiles. |

## Rules

- Never read, request, echo, or write a raw secret value. Env var NAMES only.
- Only set `default_profile` to a profile you actually wrote (or that already exists).
- Always validate with `show-effective-config` after writing.
