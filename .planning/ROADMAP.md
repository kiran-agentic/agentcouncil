# Roadmap: AgentCouncil

## Milestones

- ✅ **v1.0 Brainstorm** - Phases 1-5 (shipped 2026-04-11)
- ✅ **v1.1 Better Decisions** - Phases 6-9 (shipped 2026-04-12)
- ✅ **v1.2 Multi-Backend & OSS Release** - Phases 10-17 (shipped 2026-04-13)
- ✅ **v1.3 Kiro CLI Provider** - Phases 18-20 (shipped 2026-04-13)
- ✅ **v1.4 Unified Provider Pipeline** - Phases 21-25 (shipped 2026-04-13)
- 🔲 **v2.0 Autopilot** - Phases 26-34 (in progress)

## Phases

<details>
<summary>✅ v1.0 Brainstorm (Phases 1-5) - SHIPPED 2026-04-11</summary>

### Phase 1: Schemas
**Goal**: Typed data models every other phase depends on
**Plans**: 1 plan

Plans:
- [x] 01-01: Core schema definitions

### Phase 2: Adapter Layer
**Goal**: Abstract LLM backend calls so protocol logic is provider-agnostic
**Plans**: 1 plan

Plans:
- [x] 02-01: Adapter interface and implementations

### Phase 3: Brief Preparation
**Goal**: Contamination-safe brief that feeds the outside agent
**Plans**: 1 plan

Plans:
- [x] 03-01: Brief preparation logic

### Phase 4: Deliberation Engine
**Goal**: 4-round protocol producing the consensus artifact
**Plans**: 2 plans

Plans:
- [x] 04-01: Protocol implementation
- [x] 04-02: Consensus artifact output

### Phase 5: MCP Server
**Goal**: Brainstorm exposed as a tool callable from Claude Code
**Plans**: 2 plans

Plans:
- [x] 05-01: MCP server
- [x] 05-02: Skill path

</details>

<details>
<summary>✅ v1.1 Better Decisions (Phases 6-9) - SHIPPED 2026-04-12</summary>

### Phase 6: Common Deliberation Framework
**Goal**: Shared envelope, transcript, session management, and error handling
**Plans**: 2 plans

Plans:
- [x] 06-01: Common framework
- [x] 06-02: Session management

### Phase 7: Review
**Goal**: Structured artifact critique with severity findings and evaluative-only verdict
**Plans**: 2 plans

Plans:
- [x] 07-01: Review models
- [x] 07-02: Review function + tool + skill

### Phase 8: Decide
**Goal**: Structured option comparison, assessment, and selection with constrained outcomes
**Plans**: 2 plans

Plans:
- [x] 08-01: Decide models
- [x] 08-02: Decide function + tool + skill

### Phase 9: Challenge
**Goal**: Adversarial assumption stress-testing with failure mode analysis and readiness verdict
**Plans**: 2 plans

Plans:
- [x] 09-01: Challenge models
- [x] 09-02: Challenge function + tool + skill

</details>

<details>
<summary>✅ v1.2 Multi-Backend & OSS Release (Phases 10-17) - SHIPPED 2026-04-13</summary>

### Phase 10: Config System
**Goal**: Users can configure named backend profiles and AgentCouncil resolves the correct backend at runtime
**Plans**: 2 plans

Plans:
- [x] 10-01-PLAN.md — Core config module: BackendProfile, AgentCouncilConfig, ProfileLoader with TDD tests
- [x] 10-02-PLAN.md — show-effective-config MCP tool with source attribution

### Phase 11: Provider ABC + Read-Only Tool Harness
**Goal**: The OutsideProvider contract is defined and the read-only deliberation harness is secure and resilient
**Plans**: 3 plans

Plans:
- [x] 11-01-PLAN.md — OutsideProvider ABC, response models, StubProvider, pyproject extras
- [x] 11-02-PLAN.md — OutsideRuntime with security, tool loop, budget, and retry
- [x] 11-03-PLAN.md — Textual action protocol and integration degradation tests

### Phase 12: OutsideRuntime + OutsideSession
**Goal**: The full provider-runtime-session stack composes correctly, backward compatibility is preserved, and transcript metadata is populated
**Plans**: 2 plans

Plans:
- [x] 12-01-PLAN.md — OutsideSession lifecycle, OutsideSessionAdapter shim, AgentAdapter deprecation warning
- [x] 12-02-PLAN.md — TranscriptMeta extension and metadata propagation through all protocol engines

### Phase 13: Ollama + OpenRouter Providers
**Goal**: Raw LLMs reachable via Ollama and OpenRouter can participate in deliberations
**Plans**: 2 plans

Plans:
- [x] 13-01-PLAN.md — OllamaProvider implementation, tests, pyproject.toml ollama extra
- [x] 13-02-PLAN.md — OpenRouterProvider implementation, tests, __init__.py re-exports

### Phase 14: Bedrock Provider
**Goal**: AWS Bedrock models can participate in deliberations with correct credential handling
**Plans**: 1 plan

Plans:
- [x] 14-01-PLAN.md — BedrockProvider implementation, message normalization, contract tests

### Phase 15: MCP Integration + Skill Migration
**Goal**: All deliberation tools and skills use the uniform session API with no backend-specific branching
**Plans**: 2 plans

Plans:
- [x] 15-01-PLAN.md — Provider factory, session registry, and 4 new MCP session tools
- [x] 15-02-PLAN.md — Skill migration to uniform session API with async brainstorm

### Phase 16: Conformance Certification
**Goal**: Any backend can be certified for protocol compatibility and gates are enforced before deliberations run
**Plans**: 2 plans

Plans:
- [x] 16-01-PLAN.md — Certifier module: CertificationResult, CertificationCache, ConformanceCertifier, stale warning
- [x] 16-02-PLAN.md — Protocol gates in review_tool and challenge_tool with integration tests

### Phase 17: Documentation + OSS Packaging + Release
**Goal**: The repository is ready for public release with complete documentation and correct packaging metadata
**Plans**: 3 plans

Plans:
- [x] 17-01-PLAN.md — Rewrite BACKENDS.md and ARCHITECTURE.md for v1.2 architecture
- [x] 17-02-PLAN.md — Version alignment, .gitignore, PROTOCOLS.md and CONTRIBUTING.md updates
- [x] 17-03-PLAN.md — README.md update for multi-backend release

</details>

<details>
<summary>✅ v1.3 Kiro CLI Provider (Phases 18-20) - SHIPPED 2026-04-13</summary>

### Phase 18: KiroProvider Implementation
**Goal**: Kiro CLI participates in deliberations as a fully integrated outside agent backend
**Plans**: 2 plans

Plans:
- [x] 18-01: BackendProfile extension (cli_path, auth_token_env) + _make_provider() Kiro dispatch
- [x] 18-02: KiroProvider core — ACP subprocess, session lifecycle, permission denial, history corruption handling

### Phase 19: Contract Tests + Backward Compatibility
**Goal**: KiroProvider behavior is verified by mock-based tests and existing tests continue passing
**Plans**: 2 plans

Plans:
- [x] 19-01: ACP contract tests and two-process teardown tests
- [x] 19-02: Full test suite backward compatibility validation

### Phase 20: Documentation
**Goal**: Users know how to set up and use the Kiro backend, including its headless limitations
**Plans**: 1 plan

Plans:
- [x] 20-01: BACKENDS.md Kiro section + README.md backend table update

</details>

<details>
<summary>✅ v1.4 Unified Provider Pipeline (Phases 21-25) - SHIPPED 2026-04-13</summary>

### Phase 21: Provider Capabilities + New Providers
**Goal**: CodexProvider and ClaudeProvider are first-class OutsideProviders with declared capability metadata, and `_make_provider()` dispatches to them correctly
**Depends on**: Phase 20 (v1.3 complete)
**Requirements**: UPROV-01, UPROV-02, UPROV-03, UPROV-04
**Success Criteria** (what must be TRUE):
  1. Running a deliberation with `backend=codex` launches a persistent `codex mcp-server` process managed by CodexProvider, not the legacy adapter
  2. Running a deliberation with `backend=claude` uses `claude --print --session-id` for resumed one-shot turns
  3. Calling `_make_provider("codex")` and `_make_provider("claude")` both return OutsideProvider instances without falling through to the legacy resolver
  4. Each provider exposes `session_strategy`, `workspace_access`, and `supports_runtime_tools` attributes readable as metadata
**Plans**: 2 plans

Plans:
- [x] 21-01-PLAN.md — Capability metadata on all providers + CodexProvider + ClaudeProvider --session-id
- [x] 21-02-PLAN.md — _make_provider() dispatch for codex/claude + get_outside_backend_info update

### Phase 22: Session Mode Changes
**Goal**: OutsideSession sends only the latest prompt to persistent providers and replays full history only for stateless providers, with capabilities exposed via `get_outside_backend_info`
**Depends on**: Phase 21
**Requirements**: USESS-01, USESS-02, USESS-03
**Success Criteria** (what must be TRUE):
  1. A deliberation with Codex or Claude sends a single prompt per turn to the provider — not the full accumulated history
  2. A deliberation with Ollama, OpenRouter, or Bedrock continues to replay the full message history on each turn (existing behavior unchanged)
  3. Calling `get_outside_backend_info` from a skill returns `session_strategy`, `workspace_access`, and `supports_runtime_tools` for the active provider
**Plans**: 1 plan

Plans:
- [x] 22-01-PLAN.md — Session strategy branching in OutsideSession.call() + capability derivation from provider

### Phase 23: Skill Unification
**Goal**: All four skills use only the AgentCouncil session API with no direct backend tool calls, and adapt their prompt construction to provider capabilities
**Depends on**: Phase 21, Phase 22
**Requirements**: USKIL-01, USKIL-02, USKIL-03
**Success Criteria** (what must be TRUE):
  1. None of the four skill files (brainstorm, review, decide, challenge) contain any direct `mcp__codex__codex` or `mcp__agentcouncil__outside_query` calls
  2. When using a no-workspace provider (Ollama, OpenRouter, Bedrock), skill prompts include relevant file contents inline; when using a native-workspace provider (Codex, Kiro), they do not
  3. Each skill's `allowed-tools` frontmatter lists only `outside_start`, `outside_reply`, `outside_close`, and `get_outside_backend_info` — no backend-specific tools
**Plans**: 2 plans

Plans:
- [x] 23-01-PLAN.md — Rewrite brainstorm + review skills to unified session API
- [x] 23-02-PLAN.md — Rewrite decide + challenge skills to unified session API

### Phase 24: Auto-Fallback + Backward Compatibility
**Goal**: AgentCouncil defaults to ClaudeProvider when no backend is configured, fails explicitly on missing binaries, and the `outside_query` shim and all existing tests continue working
**Depends on**: Phase 21
**Requirements**: UFALL-01, UFALL-02, UCOMPAT-01, UCOMPAT-02
**Success Criteria** (what must be TRUE):
  1. Starting a deliberation with no backend configuration (no profile, no env var) succeeds using ClaudeProvider without any user action
  2. Calling with `backend=codex` when the `codex` binary is absent raises an actionable error message — no silent fallback to another backend
  3. Calling `outside_query` via the MCP tool produces a valid deliberation result and emits a deprecation warning in the response
  4. All 493+ existing tests pass without modification after the provider and skill changes
**Plans**: 2 plans

Plans:
- [x] 24-01-PLAN.md — Default to claude + binary guards in _make_provider
- [x] 24-02-PLAN.md — outside_query async shim with deprecation notice

### Phase 25: Documentation
**Goal**: Users can understand the unified provider pipeline architecture and configure any backend from current documentation
**Depends on**: Phase 21, Phase 22, Phase 23, Phase 24
**Requirements**: UDOC-01
**Success Criteria** (what must be TRUE):
  1. BACKENDS.md describes CodexProvider and ClaudeProvider with their session strategies, workspace access modes, and the auto-fallback behavior
  2. ARCHITECTURE.md reflects the unified pipeline — single code path through OutsideProvider, capability metadata, and the deprecated `outside_query` shim
  3. README.md backend table and quick-start instructions are accurate for the v1.4 pipeline
**Plans**: 2 plans

Plans:
- [x] 25-01-PLAN.md — Update BACKENDS.md and ARCHITECTURE.md for v1.4 pipeline
- [x] 25-02-PLAN.md — Update README.md and cross-file consistency check

</details>

## Phase Details

### Phase 26: Artifact Schemas
**Goal**: All autopilot typed contracts are defined and validated so every downstream component can build against a stable interface
**Depends on**: Phase 25 (v1.4 complete)
**Requirements**: ART-01, ART-02, ART-03, ART-04, ART-05
**Success Criteria** (what must be TRUE):
  1. All ten artifact models (SpecArtifact, CodebaseResearchBrief, ClarificationPlan, SpecPrepArtifact, PlanTask, AcceptanceProbe, PlanArtifact, BuildArtifact, VerifyArtifact with CriterionVerification/CommandEvidence/ServiceEvidence, ShipArtifact, GateDecision) can be instantiated from valid Python and round-trip through JSON without data loss
  2. Constructing an artifact with a constraint violation (empty requirements list, mismatched IDs, negative retry count) raises a Pydantic ValidationError at construction time — not silently
  3. Transition invariant helpers (e.g., `validate_lineage`) are callable with two artifacts and raise ValueError on spec_id/plan_id mismatch
  4. Unit tests cover every model_validator path with both valid and invalid inputs, all passing
**Plans**: 2 plans

Plans:
- [x] 26-01-PLAN.md — Spec-side artifact models (SpecArtifact through PlanArtifact) + package init + tests
- [x] 26-02-PLAN.md — Output-side artifact models (BuildArtifact through GateDecision) + transition helpers + tests

### Phase 27: Manifest Schema + Loader
**Goal**: Stage contracts are machine-readable and the discovery/validation layer rejects misconfigured workflows before any execution begins
**Depends on**: Phase 26
**Requirements**: ORCH-01, ORCH-02
**Success Criteria** (what must be TRUE):
  1. The loader discovers all `manifest.yaml` files under `autopilot/workflows/` and builds a stage registry without manual registration
  2. A manifest referencing an unknown artifact type or a non-existent stage in `allowed_next` causes the loader to raise a descriptive error at startup — not at runtime
  3. A valid manifest with all required fields produces a registry entry accessible by stage name that includes both the parsed manifest and loaded workflow markdown
  4. The five default workflow directories (spec_prep, plan, build, verify, ship) each have a valid manifest that passes loader validation
**Plans**: 1 plan

Plans:
- [x] 27-01-PLAN.md — Manifest schema model, loader, five default manifests, and tests

### Phase 28: Gate Normalization Layer
**Goal**: Any protocol output can be uniformly translated to an advance/revise/block decision so the orchestrator never branches on protocol type
**Depends on**: Phase 26
**Requirements**: ORCH-04
**Success Criteria** (what must be TRUE):
  1. Passing a `ConsensusArtifact` with `status=consensus` produces `GateDecision(decision="advance")`; `status=unresolved_disagreement` produces `decision="block"`
  2. Passing a `ReviewArtifact` with `verdict=revise` produces `GateDecision(decision="revise")` with non-empty `revision_guidance`
  3. Passing an unrecognized or malformed protocol output produces `GateDecision(decision="block")` with a rationale — no exception raised
  4. Unit tests cover all five protocol types (brainstorm, review, review_loop, challenge, decide) and every mapped outcome from the normalization table
**Plans**: 1 plan

Plans:
- [x] 28-01-PLAN.md — TDD GateNormalizer: all 5 protocol types + error handling + package re-export

### Phase 29: Autopilot Run State + Persistence
**Goal**: Autopilot execution state survives process restarts and a paused run can be fully reconstructed from disk with no in-memory dependency
**Depends on**: Phase 26
**Requirements**: PERS-01, PERS-02
**Success Criteria** (what must be TRUE):
  1. Creating an AutopilotRun and persisting it writes a valid JSON file to `~/.agentcouncil/autopilot/{run_id}.json` with atomic write semantics (no partial files)
  2. Loading a persisted run and calling resume reconstructs the full artifact registry from `StageCheckpoint.artifact_snapshot` — no prior in-memory state needed
  3. Attempting to resume a run with `status=failed` raises an error with the failure reason; runs with `status=paused_for_approval` or `status=paused_for_revision` resume correctly
  4. Status transitions follow the declared state machine: `running` can advance to `paused_for_approval`, `paused_for_revision`, `completed`, or `failed` — no other transitions are valid
**Plans**: 1 plan

Plans:
- [x] 29-01-PLAN.md — TDD AutopilotRun models, persistence, state machine, resume, and __init__.py re-exports

### Phase 30: Linear Orchestrator Skeleton
**Goal**: The orchestrator can sequence stub work stages end-to-end through the full pipeline, persisting state and enforcing gate transitions, before real workflow content is added
**Depends on**: Phase 27, Phase 28, Phase 29
**Requirements**: ORCH-03, ORCH-05, PERS-04
**Success Criteria** (what must be TRUE):
  1. An end-to-end run with stub stage implementations completes the full `spec_prep → plan → review_loop gate → build → review_loop gate → verify → challenge? gate → ship` sequence and reaches `status=completed`
  2. When a gate returns `revise`, the orchestrator re-executes the preceding work stage with the revision guidance attached, then re-runs the gate — not skipping it
  3. When a gate returns `block`, the orchestrator sets `status=paused_for_approval` and halts — resuming via `autopilot_resume` continues from the blocked stage
  4. The conditional challenge gate after verify fires when `side_effect_level=external` or tier=3, and is skipped (verify advances directly to ship) for normal Tier 2 work
  5. Calling `autopilot_status`, `autopilot_start`, `autopilot_prepare`, and `autopilot_resume` via MCP returns well-formed responses reflecting current run state
**Plans**: 2 plans

Plans:
- [x] 30-01-PLAN.md — TDD LinearOrchestrator: stub stages, gate loop, conditional challenge, revise/block
- [x] 30-02-PLAN.md — MCP tools (autopilot_prepare/start/status/resume) + package re-exports

### Phase 31: Workflows + Spec Prep + Verify
**Goal**: Real execution recipes are vendored and both spec_prep and verify stages produce their full typed artifacts with working implementation logic
**Depends on**: Phase 30
**Requirements**: PREP-01, PREP-02, PREP-03, PREP-04, PREP-05, VER-01, VER-02, VER-03, VER-04, VER-05, VER-06, WORK-01, WORK-02, WORK-03, WORK-04, PERS-03
**Success Criteria** (what must be TRUE):
  1. Running `autopilot_prepare` on a real repo intent produces a `SpecPrepArtifact` with a populated `CodebaseResearchBrief` (relevant files, test commands, sensitive areas) and at most 3 blocking questions asked of the user before the spec readiness check passes
  2. The verify stage starts real services, executes real test commands, and produces a `VerifyArtifact` with per-criterion `CriterionVerification` entries containing `CommandEvidence` with actual exit codes and output — no mock substitutions at integration or e2e level
  3. When verification fails, the orchestrator sends `revision_guidance` back to the build stage and re-runs — the retry loop fires at most twice before escalating to `paused_for_approval`
  4. The plan, build, and ship workflow files include the agent-skills attribution header and the repo root contains `THIRD_PARTY_NOTICES.md`
  5. All five workflow directories (spec_prep, plan, build, verify, ship) have manifests that pass loader validation, and the end-to-end test from Phase 30 passes with real workflow content replacing stubs
**Plans**: 4 plans

Plans:
- [ ] 31-01-PLAN.md — Vendor workflow content (5 workflow.md files, 3 manifest source_provenance, THIRD_PARTY_NOTICES.md)
- [ ] 31-02-PLAN.md — prep.py spec_prep stage runner (codebase research, spec refinement, arch council, readiness check)
- [ ] 31-03-PLAN.md — verify.py + ship.py stage runners (five-level verification, evidence collection, readiness packaging)
- [ ] 31-04-PLAN.md — Orchestrator verify-to-build retry loop, server.py runner registration, integration tests

### Phase 32: Approval Boundary
**Goal**: The orchestrator never executes external side effects without explicit human authorization
**Depends on**: Phase 30
**Requirements**: SAFE-01, SAFE-02
**Success Criteria** (what must be TRUE):
  1. A stage with `side_effect_level: external` in its manifest pauses at `status=paused_for_approval` before any external action executes — approval check runs before stage execution, not after
  2. A stage with `approval_required: true` in its manifest always pauses for human approval regardless of autonomy tier
  3. Local workspace changes (`side_effect_level: local`) proceed through the pipeline without triggering an approval pause
  4. A run paused for approval can be resumed via `autopilot_resume` and continues from the exact stage where it paused
**Plans**: TBD

### Phase 33: Rule-Based Router
**Goal**: Every stage receives an autonomy tier assignment based on declared intent before execution begins, and tier promotions are sticky for the remainder of the run
**Depends on**: Phase 32
**Requirements**: SAFE-03, SAFE-04
**Success Criteria** (what must be TRUE):
  1. A stage whose `target_files` include a path matching `auth/`, `migrations/`, `infra/`, `deploy/`, or `permissions/` is classified Tier 3 — the router does not require human input to make this classification
  2. A Tier 1 stage skips all protocol gates and executes directly; a Tier 2 stage runs through the full gate pipeline; a Tier 3 stage requires council deliberation and human sign-off before execution
  3. When a stage that began at Tier 1 or Tier 2 touches an undeclared sensitive file during execution, the run promotes to the higher tier and all subsequent stages in that run use the promoted tier — no silent demotion occurs
  4. Tier classification is logged in the AutopilotRun state so the classification decision is auditable after the run completes
**Plans**: TBD

### Phase 34: Failure Handling + Dynamic Promotion
**Goal**: The system recovers gracefully from protocol timeouts, exhausted retries, and mid-execution surprises while maintaining a complete checkpoint for every partial completion
**Depends on**: Phase 33
**Requirements**: SAFE-05
**Success Criteria** (what must be TRUE):
  1. When a protocol gate times out, the orchestrator retries using the `retry_policy` from the stage manifest (`once` or `backend_fallback`) before escalating
  2. After exhausting retries, the orchestrator sets `status=paused_for_approval` and populates `AutopilotRun.failure_reason` — the run state is inspectable without re-running
  3. A run that fails mid-pipeline has a `StageCheckpoint` for each completed stage with its serialized artifact snapshot, and `autopilot_resume` continues from the last successful checkpoint — not from the beginning
  4. Dynamic tier promotion fires when the challenge gate returns `not_ready` or a review gate finds a `critical` or `high` severity finding — the promotion is reflected in the persisted run state before the next stage executes
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Schemas | v1.0 | 1/1 | Complete | 2026-04-10 |
| 2. Adapter Layer | v1.0 | 1/1 | Complete | 2026-04-10 |
| 3. Brief Preparation | v1.0 | 1/1 | Complete | 2026-04-10 |
| 4. Deliberation Engine | v1.0 | 2/2 | Complete | 2026-04-10 |
| 5. MCP Server + Skill Path | v1.0 | 2/2 | Complete | 2026-04-11 |
| 6. Common Deliberation Framework | v1.1 | 2/2 | Complete | 2026-04-12 |
| 7. Review | v1.1 | 2/2 | Complete | 2026-04-11 |
| 8. Decide | v1.1 | 2/2 | Complete | 2026-04-11 |
| 9. Challenge | v1.1 | 2/2 | Complete | 2026-04-12 |
| 10. Config System | v1.2 | 2/2 | Complete | 2026-04-12 |
| 11. Provider ABC + Tool Harness | v1.2 | 3/3 | Complete | 2026-04-12 |
| 12. OutsideRuntime + OutsideSession | v1.2 | 2/2 | Complete | 2026-04-12 |
| 13. Ollama + OpenRouter Providers | v1.2 | 2/2 | Complete | 2026-04-12 |
| 14. Bedrock Provider | v1.2 | 1/1 | Complete | 2026-04-13 |
| 15. MCP Integration + Skill Migration | v1.2 | 2/2 | Complete | 2026-04-13 |
| 16. Conformance Certification | v1.2 | 2/2 | Complete | 2026-04-13 |
| 17. Documentation + OSS Release | v1.2 | 3/3 | Complete | 2026-04-13 |
| 18. KiroProvider Implementation | v1.3 | 2/2 | Complete | 2026-04-13 |
| 19. Contract Tests + Backward Compat | v1.3 | 2/2 | Complete | 2026-04-13 |
| 20. Documentation | v1.3 | 1/1 | Complete | 2026-04-13 |
| 21. Provider Capabilities + New Providers | v1.4 | 2/2 | Complete | 2026-04-13 |
| 22. Session Mode Changes | v1.4 | 1/1 | Complete | 2026-04-13 |
| 23. Skill Unification | v1.4 | 2/2 | Complete | 2026-04-13 |
| 24. Auto-Fallback + Backward Compat | v1.4 | 2/2 | Complete | 2026-04-13 |
| 25. Documentation | v1.4 | 2/2 | Complete | 2026-04-13 |
| 26. Artifact Schemas | v2.0 | 2/2 | Complete    | 2026-04-15 |
| 27. Manifest Schema + Loader | v2.0 | 0/1 | Complete    | 2026-04-15 |
| 28. Gate Normalization Layer | v2.0 | 1/1 | Complete    | 2026-04-15 |
| 29. Autopilot Run State + Persistence | v2.0 | 0/1 | Complete    | 2026-04-15 |
| 30. Linear Orchestrator Skeleton | v2.0 | 2/2 | Complete    | 2026-04-15 |
| 31. Workflows + Spec Prep + Verify | v2.0 | 0/4 | Not started | - |
| 32. Approval Boundary | v2.0 | 0/? | Not started | - |
| 33. Rule-Based Router | v2.0 | 0/? | Not started | - |
| 34. Failure Handling + Dynamic Promotion | v2.0 | 0/? | Not started | - |

---
*Last updated: 2026-04-15 — Phase 31 planned (4 plans, 2 waves)*
