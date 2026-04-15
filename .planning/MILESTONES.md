# Milestones

## v2.0 Autopilot (Shipped: 2026-04-15)

**Phases completed:** 9 phases, 14 plans, 14 tasks

**Key accomplishments:**

- Seven spec-side Pydantic models (SpecArtifact through PlanArtifact) with field-level validators, standalone clarification validator, and 32 comprehensive unit tests — typed contract layer for all v2.0 autopilot phases
- 9 output-side Pydantic models (Build/Verify/Ship/Gate) with cross-field validators and 4 transition lineage helpers completing the full autopilot typed artifact chain
- 1. [Rule 1 - Bug] Error message split across string literal lines
- One-liner:
- Durable run state model with atomic JSON persistence, state machine enforcement, and paused-run resume with typed artifact registry reconstruction
- One-liner:
- One-liner:
- 1. [Rule 3 - Blocking] build/ directory ignored by .gitignore
- One-liner:
- One-liner:
- Verify->build retry loop in LinearOrchestrator (max 2 retries, paused_for_approval escalation) with real stage runners registered in server.py for spec_prep, verify, and ship stages
- Pre-execution approval guard on LinearOrchestrator using three-tier classification that blocks external/approval_required stages before any runner fires, with resume bypass via already-blocked checkpoint status
- One-liner:
- LinearOrchestrator extended with gate retry policy enforcement, exhaustion escalation to paused_for_approval, and gate-outcome-driven tier 3 promotion for challenge not_ready and review critical/high findings

---

## v1.3 Kiro CLI Provider (Shipped: 2026-04-13)

**Phases completed:** 3 phases, 5 plans, 9 tasks

**Key accomplishments:**

- BackendProfile extended with cli_path/auth_token_env fields (with _ENV_VAR_RE validation) and _make_provider wired to dispatch provider="kiro" to KiroProvider via lazy import
- KiroProvider implements full ACP JSON-RPC 2.0 session lifecycle (initialize -> session/new -> session/prompt -> TurnEnd) with permission denial, history corruption detection, and two-process teardown via pgrep -P + staged SIGTERM
- 8 new mock-based ACP contract tests closing all untested KiroProvider branches: permission denial in handshake phase, stdout EOF during startup, _started flag gating, sessionId wiring, pgrep fallback, force-kill on timeout, and state reset after stop
- 480 tests pass with zero failures after KiroProvider introduction; non-Kiro isolation confirmed (464/464), import side effects absent
- Commit:

---

## v1.2 Multi-Backend & OSS Release (Shipped: 2026-04-13)

**Phases completed:** 8 phases, 17 plans, 21 tasks

**Key accomplishments:**

- One-liner:
- One-liner:
- OutsideProvider ABC with async chat_complete/auth_check, ProviderResponse/ToolCall/ProviderError models, StubProvider test double, and pyproject.toml backend extras (ollama/openrouter/bedrock)
- OutsideRuntime with path traversal + symlink prevention, extension blocklist, 4 read-only tools (list_files/search_repo/read_file/read_diff), per-turn char budget, and 3-retry degradation to text-only mode
- Line-anchored regex parser for READ_FILE/LIST_FILES/SEARCH_REPO/READ_DIFF integrated into OutsideRuntime as opt-in fallback (allow_textual_protocol) with StubProvider degradation integration tests
- OutsideSession open/call/close lifecycle with replay message accumulation, OutsideSessionAdapter shim, and AgentAdapter DeprecationWarning for external subclasses
- 4 new Optional[str] fields on TranscriptMeta (outside_provider, outside_profile, outside_session_mode, outside_workspace_access) wired through all 4 protocol engines via outside_meta parameter
- One-liner:
- OpenRouterProvider with lazy client creation and JSON argument parsing, both providers re-exported from agentcouncil.providers with graceful ImportError handling
- BedrockProvider via boto3 converse() with per-invocation client creation, toolUse/toolResult normalization, and 11 contract tests covering PROV-04/05/07
- All 4 skill tools migrated to uniform session API: _make_provider + OutsideSession + OutsideSessionAdapter, with backend= param, no if/elif branching, async brainstorm()
- Conformance certifier with 4-scenario StubProvider runner, JSON cache, and protocol gate blocking prompt-only models on review/challenge
- check_certification_gate wired into review_tool and challenge_tool in server.py with ValueError propagating before legacy fallback, plus 4 server.py gate wiring integration tests (453 total tests passing)
- One-liner:
- Version string aligned to 1.2.0 across 4 packaging files, .gitignore fixed for OSS, PROTOCOLS.md documents backend= parameter and multi-backend intro, CONTRIBUTING.md updated to v1.2 patterns (StubProvider, session tools, lazy imports, provider extras)
- README.md updated for v1.2 public release: 453 passing tests badge, 5-backend comparison table with profile config selection, and StubProvider dev setup

---

## v1.1 Better Decisions (Shipped: 2026-04-12)

**Phases completed:** 4 phases, 8 plans, 12 tasks

**Key accomplishments:**

- Generic DeliberationResult[T] envelope with Transcript, TranscriptTurn, SourceRef, and stub artifacts (ReviewArtifact, DecideArtifact, ChallengeArtifact) with Pydantic model_validator invariant enforcement
- CodexSession async context manager for persistent Codex MCP sessions and run_deliberation() dual-independent protocol runner with comprehensive error handling (partial_failure, unresolved_disagreement, input validation)
- ReviewInput, Finding, and typed ReviewArtifact models with Literal enum validation and JSON roundtrip correctness
- review() function calling run_deliberation with evaluative-only prompts, factual-only director brief, disputed findings preserved, MCP tool and /review skill
- Typed Pydantic models for Decide function with Literal-constrained disposition/confidence and disposition-based outcome invariants enforced via model_validator
- decide() function calling run_deliberation with factual-only input, option-constrained synthesis requiring assumptions/tradeoffs/confidence for every option, wired as MCP tool and /decide skill
- Typed ChallengeInput, FailureMode models and ChallengeArtifact upgrade from list[dict] to list[FailureMode] with readiness invariants enforced via Pydantic validators
- challenge() function with adversarial attack-defense prompts, MCP tool, and /challenge skill -- completing the Challenge phase

---
