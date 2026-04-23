# Suggested Commands

## Environment Setup
```bash
uv sync --extra dev          # Install all dev dependencies into .venv
source .venv/bin/activate    # Activate venv (or use uv run)
uv sync --extra all-backends # Install all optional backend extras
```

## Running Tests
```bash
uv run pytest                          # Run all non-real tests (default: excludes @real marker)
uv run pytest tests/test_schemas.py    # Run a specific test file
uv run pytest -m real                  # Run real integration tests (needs codex/claude CLI)
uv run pytest -v                       # Verbose output
uv run pytest --timeout=30             # With timeout
```

## Running the MCP Server
```bash
bash scripts/start-server.sh           # Launch the MCP server
uv run python -m agentcouncil.server   # Direct launch (if applicable)
```

## CLI Inspector
```bash
agentcouncil                           # Run the inspector CLI entry point
uv run agentcouncil                    # Via uv
```

## Code Quality (no linter/formatter configured in pyproject.toml — use manually)
```bash
uv run ruff check .                    # Lint (if ruff installed)
uv run ruff format .                   # Format (if ruff installed)
```

## Git
```bash
git status
git log --oneline -10
git diff
```

## Installing in Editable Mode
```bash
uv pip install -e .                    # Editable install
pip install -e ".[dev]"               # With dev extras
```
