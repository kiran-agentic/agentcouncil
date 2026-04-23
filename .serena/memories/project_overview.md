# AgentCouncil — Project Overview

## Purpose
Multi-agent deliberation and governance protocols for AI coding assistants. Tagline: "Independence before convergence." Provides structured deliberation (brainstorm, review, decide, challenge) and autonomous delivery (autopilot) as an MCP server that plugs into Claude Code and other agents.

## Version & Status
- Current version: 0.2.0 (Beta)
- Python ≥ 3.12 required
- GitHub: https://github.com/kiran-agentic/agentcouncil

## Core Concepts
- **Outside agent**: An independent agent (e.g. codex, claude, ollama) that provides a second perspective
- **Protocols**: brainstorm, review, decide, challenge — each runs a structured deliberation
- **Autopilot**: Council-governed autonomous delivery pipeline
- **Journal**: Persistent session log of all deliberations
- **Skill mode**: Primary user-facing mode via Claude Code skill files in `skills/`

## Entry Points
- MCP server: `agentcouncil/server.py` (FastMCP-based, all tools registered here)
- CLI inspector: `agentcouncil = "agentcouncil.inspector:main"`
- Server launch: `scripts/start-server.sh`

## Tech Stack
- Python 3.12+
- Pydantic v2 + pydantic-settings for models and config
- FastMCP ≥ 3.2.3 for MCP server
- pytest + pytest-asyncio for tests
- uv for dependency management and venv (`.venv/`)
- Optional backends: ollama, openrouter, bedrock

## Architecture Layers
- `agentcouncil/schemas.py` — Pydantic models (TranscriptTurn, Transcript, artifacts, etc.)
- `agentcouncil/adapters.py` — Legacy AgentAdapter + VALID_BACKENDS + resolve helpers
- `agentcouncil/providers/` — New OutsideProvider implementations (claude, codex, ollama, openrouter, bedrock, kiro)
- `agentcouncil/config.py` — 5-level config precedence (BackendProfile, AgentCouncilConfig, ProfileLoader)
- `agentcouncil/deliberation.py`, `review.py`, `decide.py`, `challenge.py` — Protocol logic
- `agentcouncil/autopilot/` — Autonomous delivery pipeline modules
- `agentcouncil/server.py` — MCP tool registrations (FastMCP)
- `agentcouncil/journal.py` — Session persistence
- `skills/` — Claude Code skill SKILL.md files (brainstorm, review, decide, challenge, autopilot, inspect)

## Config
Project config at `.agentcouncil.json` (default_profile + named profiles).
Global config at `~/.agentcouncil.json`.
Default profile in this project: `codex`.
