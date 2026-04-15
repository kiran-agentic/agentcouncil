# Requirements: AgentCouncil

**Defined:** 2026-04-15
**Core Value:** Independence before convergence — agents must think independently before seeing each other's proposals

## v2.0 Requirements

Requirements for Autopilot — Council-Governed Autonomous Delivery. Each maps to roadmap phases.

### Artifact Contracts

- [x] **ART-01**: Typed Pydantic models for all autopilot artifacts (SpecArtifact, SpecPrepArtifact, PlanArtifact, BuildArtifact, VerifyArtifact, ShipArtifact, GateDecision)
- [x] **ART-02**: Model invariants enforced via model_validator for self-contained checks
- [x] **ART-03**: Transition invariant helpers as standalone functions for cross-artifact lineage validation
- [x] **ART-04**: AcceptanceProbe model on PlanArtifact mapping every acceptance criterion to a verification strategy
- [x] **ART-05**: VerifyArtifact with per-criterion CriterionVerification, CommandEvidence, and ServiceEvidence

### Stage Orchestration

- [x] **ORCH-01**: Manifest YAML schema with stage_type, input/output artifact, default_gate, side_effect_level, retry_policy
- [x] **ORCH-02**: Manifest loader discovers workflow directories, validates contracts, builds stage registry
- [x] **ORCH-03**: Linear orchestrator state machine threads typed artifacts through spec_prep → plan → build → verify → ship
- [x] **ORCH-04**: Gate normalization maps protocol outputs (ConsensusArtifact, ReviewArtifact, ConvergenceResult, ChallengeArtifact, DecideArtifact) to advance/revise/block
- [x] **ORCH-05**: Conditional challenge gate after verify fires only for high-risk work (sensitive paths, external side effects, Tier 3, explicit request)

### Spec Prep

- [ ] **PREP-01**: Codebase research identifies target files, existing patterns, test infrastructure, sensitive areas, verification environment
- [ ] **PREP-02**: Interactive spec refinement asks 0-3 blocking questions with 5 hard max, presents full understanding with assumptions
- [ ] **PREP-03**: Conditional architecture council brainstorm triggers for cross-module, schema/API, security, or ambiguous work
- [ ] **PREP-04**: Spec readiness check validates requirements, acceptance criteria, verification feasibility, and delivery clarity before autonomous execution
- [ ] **PREP-05**: SpecPrepArtifact distinguishes binding decisions from advisory context

### Verification

- [ ] **VER-01**: Five verification levels: static, unit, integration, smoke, e2e
- [ ] **VER-02**: Real integration testing — start services, hit real endpoints, check real state (no mocks at integration/e2e level)
- [ ] **VER-03**: Per-acceptance-criterion evidence with structured command results, service lifecycle, and artifacts
- [ ] **VER-04**: Verify → build retry loop with actionable failure evidence (max 2 retries, hard cap 3)
- [ ] **VER-05**: Generated integration probes when project has no existing test infrastructure
- [ ] **VER-06**: Playwright/browser automation for frontend changes

### Autonomy & Safety

- [ ] **SAFE-01**: Three-tier autonomy model with per-stage classification (executor/council/approval-gated)
- [ ] **SAFE-02**: Approval boundary blocks external side effects pending human approval
- [ ] **SAFE-03**: Rule-based router classifies stages by declared intent (target_files, side_effect_level)
- [ ] **SAFE-04**: Dynamic tier promotion when sensitive files detected mid-execution (sticky for remainder of run)
- [ ] **SAFE-05**: Failure handling with retry policy, escalation, and partial completion checkpoints

### Persistence & Delivery

- [x] **PERS-01**: AutopilotRun state persisted to ~/.agentcouncil/autopilot/{run_id}.json with atomic writes
- [x] **PERS-02**: Resume from paused_for_approval and paused_for_revision with artifact reconstruction
- [ ] **PERS-03**: Ship produces structured readiness packet with branch/SHA, verification status, release notes, rollback plan
- [x] **PERS-04**: MCP tools: autopilot_prepare, autopilot_start, autopilot_status, autopilot_resume

### Workflow Content

- [ ] **WORK-01**: Vendored agent-skills workflows (plan, build, ship) with MIT attribution and editorial adaptation
- [ ] **WORK-02**: AgentCouncil-native spec_prep workflow implementing research-first questioning
- [ ] **WORK-03**: AgentCouncil-native verify workflow implementing 5-level testing pyramid
- [ ] **WORK-04**: Agent-skills repo (https://github.com/addyosmani/agent-skills) used as standing reference throughout all phases

## Future Requirements

Deferred beyond v2.0. Tracked but not in current roadmap.

### Delegation
- **DELEG-01**: Scoped task assignment with ownership, boundaries, and return paths
- **DELEG-02**: Worker/task artifact model for delegated work

### Memory
- **MEM-01**: Cross-run memory (prior autopilot decisions informing new runs)
- **MEM-02**: Journal search (FTS5 over autopilot runs and protocol sessions)

### Advanced Ingestion
- **INGEST-01**: Full vision-to-spec ingestion from multi-page vision documents
- **INGEST-02**: Branching/parallel stage execution

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Actual production deploys in MVP | Ship produces recommendation only — Tier 3 approval for real deploys |
| SkillSpec abstraction / general importer | Defer until reuse patterns emerge — direct copy is sufficient |
| `decide` protocol as default gate | Only on-demand when explicit competing options exist |
| Multi-backend gate execution | Different protocols on different backends — future |
| Non-linear/branching stage execution | MVP is linear only |
| Council overriding failed verification | Deterministic checks own pass/fail — council classifies ambiguity only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ART-01 | Phase 26 | Complete |
| ART-02 | Phase 26 | Complete |
| ART-03 | Phase 26 | Complete |
| ART-04 | Phase 26 | Complete |
| ART-05 | Phase 26 | Complete |
| ORCH-01 | Phase 27 | Complete |
| ORCH-02 | Phase 27 | Complete |
| ORCH-03 | Phase 30 | Complete |
| ORCH-04 | Phase 28 | Complete |
| ORCH-05 | Phase 30 | Complete |
| PREP-01 | Phase 31 | Pending |
| PREP-02 | Phase 31 | Pending |
| PREP-03 | Phase 31 | Pending |
| PREP-04 | Phase 31 | Pending |
| PREP-05 | Phase 31 | Pending |
| VER-01 | Phase 31 | Pending |
| VER-02 | Phase 31 | Pending |
| VER-03 | Phase 31 | Pending |
| VER-04 | Phase 31 | Pending |
| VER-05 | Phase 31 | Pending |
| VER-06 | Phase 31 | Pending |
| SAFE-01 | Phase 32 | Pending |
| SAFE-02 | Phase 32 | Pending |
| SAFE-03 | Phase 33 | Pending |
| SAFE-04 | Phase 33 | Pending |
| SAFE-05 | Phase 34 | Pending |
| PERS-01 | Phase 29 | Complete |
| PERS-02 | Phase 29 | Complete |
| PERS-03 | Phase 31 | Pending |
| PERS-04 | Phase 30 | Complete |
| WORK-01 | Phase 31 | Pending |
| WORK-02 | Phase 31 | Pending |
| WORK-03 | Phase 31 | Pending |
| WORK-04 | Phase 31 | Pending |

**Coverage:**
- v2.0 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0

---
*Requirements defined: 2026-04-15*
*Last updated: 2026-04-15 — traceability expanded to per-requirement rows after roadmap creation*
