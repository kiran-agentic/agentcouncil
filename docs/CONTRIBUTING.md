# Contributing to AgentCouncil

Thanks for your interest in contributing!

## Getting started

1. Fork and clone the repository
2. Install in development mode: `pip install -e ".[dev,ollama]"` (add backend extras as needed: `ollama`, `openrouter`, `bedrock`, or `all-backends`)
3. Run tests: `pytest`

## Development

- Python 3.12+ required
- Tests use `StubProvider` so you don't need Codex/Claude CLIs installed
- Run `pytest -m real` to run integration tests (requires `claude` and `codex` CLIs on PATH)

## Making changes

1. Create a branch from `main`
2. Make your changes
3. Ensure tests pass: `pytest`
4. Submit a pull request

## Adding a new protocol

Each protocol has two parts: a skill definition (primary) and optionally a library-mode engine (secondary). The skill definition is the required part — it's what users invoke via `/command`. The library-mode engine is optional and provides an MCP tool for programmatic use.

**Skill definition (primary — required):**

1. Create `skills/<protocol>/SKILL.md` with frontmatter and protocol instructions
2. Define Claude Code's role and the outside agent's role (see existing skills as templates)
3. Add `outside_start`, `outside_reply`, `outside_close`, and `get_outside_backend_info` to `allowed-tools` for backend-agnostic session management
4. Include a Step 0 that calls `get_outside_backend_info` to check `workspace_access` — adapt prompt construction based on whether the outside agent can read files natively

**Library-mode engine (secondary — optional):**

1. Define input/output schemas in `schemas.py`
2. Implement the protocol engine in a new module (see `review.py` as a template)
3. Register the MCP tool in `server.py`
4. Add tests using `StubProvider` (from `agentcouncil.providers.base`)

## Code style

- Type hints on all public functions
- Pydantic models for all structured data crossing API boundaries
- Providers instantiated via `_make_provider()` with lazy imports — never at module level

## Adding a new provider

When adding support for a new backend SDK:

1. Implement the `OutsideProvider` ABC in `agentcouncil/providers/<name>.py` — do NOT extend `AgentAdapter` (it is deprecated)
2. Declare capability metadata as class-level attributes: `session_strategy` (`"persistent"` or `"replay"`), `workspace_access` (`"native"`, `"assisted"`, or `"none"`), `supports_runtime_tools` (`True` or `False`)
3. Add the SDK as an optional extra in `pyproject.toml` (e.g. `[project.optional-dependencies]` section)
4. Use lazy imports inside the provider module so users without the SDK installed are not affected at import time
5. Register the provider name in `_make_provider()` in `server.py` — add both string dispatch and BackendProfile dispatch branches
6. Add tests using `StubProvider` for the protocol logic; add a `pytest -m real` test for actual SDK interaction

## Troubleshooting

**Debugging backend configuration:** Use the `show-effective-config` MCP tool to see where each config value came from (skill arg, env var, project config, global config, or default).

**Common issues:**
- `ProviderError: codex binary not found` — install the Codex CLI: `npm install -g @openai/codex`
- `ProviderError: claude binary not found` — install Claude Code or ensure `claude` is on PATH
- Backend returning unexpected responses — check conformance certification: the model may not support function calling

## Reporting issues

Open an issue at https://github.com/kiran-agentic/agentcouncil/issues
