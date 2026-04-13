# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in AgentCouncil, please report it through [GitHub Security Advisories](https://github.com/kiran-agentic/agentcouncil/security/advisories/new).

**Do not** open a public issue for security vulnerabilities.

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

## Trust Model

AgentCouncil has two distinct security boundaries depending on the backend type:

### Native backends (Claude, Codex, Kiro)

Native backends run as local processes with their own tool permissions. They can read and write files in the workspace using their own built-in tools. AgentCouncil does not restrict their capabilities — they operate with the same trust level as any local CLI tool you run.

**Implication:** A native backend has the same access as the user running it. Do not use native backends in environments where the outside agent should not have write access.

### Assisted backends (Ollama, OpenRouter, Bedrock)

Assisted backends use AgentCouncil's read-only tool harness (`OutsideRuntime`). They can only inspect the workspace through four tools: `list_files`, `search_repo`, `read_file`, `read_diff`. All access is read-only — no writes, no command execution.

**Security controls:**
- Path traversal prevention via `os.path.realpath()` — catches `../` and symlink escapes
- File blocklist: `.env`, `.env.*`, `.netrc`, `.npmrc`, `.git-credentials`, `.pypirc`, SSH keys (`id_rsa`, `id_ed25519`, etc.), and certificate files (`.pem`, `.key`, `.p12`, etc.)
- Directory blocklist: `.ssh/`, `.aws/`, `.docker/`, `.gnupg/`
- Per-turn character budget (100 KB default)
- 3-retry tool call limit per turn

**Implication:** Assisted backends transmit file contents to remote APIs (OpenRouter, Bedrock). The blocklist prevents reading obvious secrets, but workspace files sent to these backends leave your machine. Use native backends for sensitive codebases.

## Scope

- **Read-only tool harness** (`OutsideRuntime`): Path traversal prevention, file/directory blocklist, symlink escape detection
- **Credential handling**: API keys read from environment variables, never stored in config files
- **Native backend isolation**: Not enforced by AgentCouncil — these backends manage their own permissions

## Out of Scope

- Vulnerabilities in upstream dependencies (report to the upstream project)
- Vulnerabilities in the LLM backends themselves (Codex, Claude, Ollama, etc.)
- Social engineering attacks via crafted prompts (prompt injection is an inherent LLM limitation)
