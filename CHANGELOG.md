# Changelog

## 0.1.0 (2026-04-13)

First public release.

### Features

- **Four deliberation protocols:** brainstorm, review, decide, challenge — each with distinct roles for Claude Code and the outside agent
- **Seven backend providers:** Claude (default), Codex, Ollama, OpenRouter, Bedrock, Kiro, plus StubProvider for testing
- **Provider capability metadata:** session_strategy, workspace_access, supports_runtime_tools — skills adapt automatically
- **Session API:** outside_start/outside_reply/outside_close for multi-turn deliberations
- **Named backend profiles** via `.agentcouncil.json` with precedence resolution
- **Auto-fallback** to Claude when no backend configured
- **Read-only tool harness** for workspace inspection by outside agents (path security, extension blocklist, token budget)
- **Conformance certification** for gated protocols (review, challenge)
- **Claude Code plugin** install via `/plugin marketplace add`
