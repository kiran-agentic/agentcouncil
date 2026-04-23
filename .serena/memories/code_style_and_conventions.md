# Code Style & Conventions

## General
- Python 3.12+ features used freely (match, type aliases, etc.)
- `from __future__ import annotations` at top of most modules
- Type hints on all public functions and class fields
- Pydantic v2 models for all data structures (no dataclasses for domain objects)
- `__all__` defined in every module

## Naming
- snake_case for functions, variables, modules
- PascalCase for classes
- UPPER_SNAKE_CASE for true constants
- Private helpers prefixed with `_` (e.g. `_make_provider`, `_resolve_workspace`)
- MCP tool functions suffixed with `_tool` (e.g. `brainstorm_tool`, `review_tool`)

## Docstrings
- Module-level docstrings describe the module purpose and exported symbols
- Class docstrings describe fields and important behaviour
- Method docstrings only where non-obvious; no redundant "getter" docstrings
- Format: plain prose, not NumPy/Google style

## Comments
- Inline comments used sparingly; only when WHY is non-obvious
- Requirement IDs referenced in comments (e.g. `# CFG-01`, `# CFG-06`)

## Imports
- stdlib → third-party → local, separated by blank lines
- Local imports use absolute paths (`from agentcouncil.x import Y`)
- Lazy local imports inside functions when needed to avoid circular deps

## Error Handling
- Custom exceptions defined per module (e.g. `AdapterError`)
- Pydantic `model_validator` for input validation
- Don't catch broad exceptions; let them propagate unless a specific recovery is needed

## Tests
- pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- Tests marked `@pytest.mark.real` require live CLI tools and are excluded by default
- Fixtures in `tests/conftest.py`
- One test file per module (e.g. `test_schemas.py`, `test_config.py`)
