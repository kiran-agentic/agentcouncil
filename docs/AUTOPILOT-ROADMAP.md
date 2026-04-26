# Autopilot Roadmap

*Council-governed autonomous software delivery. User defines what; the council handles how.*

**Status:** Design complete (brainstorm consensus, review-hardened). Implementation not started.
**Date:** 2026-04-15
**Origin:** Four AgentCouncil brainstorm sessions + two review loops (Claude + Codex)

---

## 1. What Autopilot Is

Autopilot is AgentCouncil's autonomous execution mode. The user engages during spec preparation, then the system takes over — planning, building, reviewing, and shipping through council-governed stage transitions.

**MVP entrypoint:** User provides a rough description or partial `SpecArtifact`. The `spec_prep` stage enriches it into an autonomy-ready `SpecPrepArtifact` through codebase research, targeted questioning, and optional architecture review. After spec prep, the user disengages.

**The composition:**
- **Agent-skills** (Addy Osmani) supplies execution recipes — proven workflow instructions for each development stage
- **AgentCouncil protocols** supply governance — multi-agent deliberation at every stage transition
- **A new orchestrator layer** threads artifacts through work stages and gates transitions through protocols

No single agent's judgment goes unchecked. Every stage transition passes through an independent deliberation gate.

**Two kinds of stages:**
- **Work stages** produce typed artifacts (spec, plan, code). The orchestrating agent executes the workflow recipe.
- **Gate stages** produce transition decisions (advance/revise/block). An independent agent evaluates via AgentCouncil protocols.

```
User provides rough description or partial spec
       │
       ▼
┌──────────────────────────────────────┐
│  SPEC PREP (interactive work stage)  │
│  1. Codebase research (autonomous)   │
│  2. Targeted questions (0-3, user)   │
│  3. Architecture review (conditional)│
│  Output: SpecPrepArtifact            │
└──────────────┬───────────────────────┘
               │
               ▼  ← user disengages here
┌─────────────────────────────────────────────────┐
│              AUTOPILOT ORCHESTRATOR              │
│  (sequences work stages, threads artifacts,      │
│   injects gate stages, enforces approval bounds) │
└──┬──────────┬──────────┬──────────┬─────────────┘
   │          │          │          │
   ▼          ▼          ▼          ▼
┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐
│ PLAN │  │BUILD │  │VERIFY│  │ SHIP │
│(work)│  │(work)│  │(work)│  │(work)│
└──┬───┘  └──┬───┘  └──┬───┘  └──────┘
   │          │          │
   ▼          ▼          ▼
┌──────┐  ┌──────┐  ┌──────┐
│REVIEW│  │REVIEW│  │CHALL?│
│ LOOP │  │ LOOP │  │ENGE  │
│(gate)│  │(gate)│  │(gate)│
└──────┘  └──────┘  └──────┘
```

**Gate placement rationale:**
- `review_loop` after plan and build: independent agent critiques code quality and plan quality
- `challenge?` after verify (conditional): stress-tests "does this really work?" — only fires for high-risk work
- Ship has no gate — it's deterministic readiness packaging after everything is already verified and challenged

## 2. Why This Architecture

### The problem with agent-skills alone

Agent-skills encodes 20 engineering workflows covering the full dev lifecycle. But phase transitions are judgment calls by a single agent. The agent decides when a spec is "good enough," when a plan is "complete enough," when code is "ready for review." No structural check exists. The agent can rationalize skipping steps.

### The problem with AgentCouncil alone

AgentCouncil provides four deliberation protocols, but they're isolated invocations with no workflow context. You can brainstorm a spec, but the system doesn't know the next step is planning, or that the plan should be reviewed before build begins.

### The composition

Agent-skills becomes the workflow content (what to do at each stage). AgentCouncil protocols become the gates (whether the work is allowed to advance). A new orchestrator layer connects them.

**Key design principle:** Copied workflow markdown is accelerant, not architecture. The architecture is typed artifacts plus orchestration policy.

## 3. Core Design Decisions

These were resolved through structured deliberation (Claude + Codex). Each represents consensus.

### 3.1 Agent-skills as execution recipes, not the workflow graph

Agent-skills is a useful lifecycle taxonomy, but not a durable workflow graph. It does not define typed artifacts, transition contracts, skip rules, rollback semantics, or escalation behavior. AgentCouncil must own the workflow schema.

**Decision:** Agent-skills informs the workflow graph; it does not *be* the graph. AgentCouncil owns typed artifacts, transition contracts, and gate policies. Agent-skills supplies the execution recipe content within each stage.

**Standing reference:** https://github.com/addyosmani/agent-skills should be consulted throughout all implementation phases — not just during workflow copying. These are battle-tested, production-grade engineering workflows. Before writing any execution logic, verification strategy, or workflow instruction from scratch, check whether agent-skills already has a proven pattern for it. This applies to:
- Workflow recipes (plan, build, ship — copied in Phase 6)
- Verification strategies (TDD skill has proven test patterns)
- Code review criteria (code-review-and-quality skill)
- Security hardening (security-and-hardening skill)
- Debugging patterns (debugging-and-error-recovery skill)
- Context engineering (context-engineering skill for spec_prep research)
- Shipping checklists (shipping-and-launch skill)

### 3.2 Copy skills directly, not SkillSpec + importer

The original plan (build a SkillSpec Pydantic model + general importer + compatibility layer) was over-engineered for the starting point. Direct copying is faster and proves the concept sooner.

**Decision:** Copy a curated subset of agent-skills directly into `agentcouncil/autopilot/workflows/`. Modify in-place. Defer SkillSpec abstraction until repeated reuse patterns emerge.

**License:** Agent-skills is MIT licensed (Addy Osmani, 2025). AgentCouncil is Apache 2.0. MIT → Apache 2.0 is fully compatible. Retain MIT copyright notice per-file plus a THIRD_PARTY_NOTICES.md at repo root.

### 3.3 Gate stage transitions, not every skill

Dense per-skill gating causes over-deliberation and latency death. Protocols should gate stage transitions and risk boundaries only.

**Decision:** Gate at stage boundaries (plan→build, build→ship). Reserve `challenge` for irreversible/security-critical/launch transitions. Skip `decide` in MVP unless explicit competing options exist.

### 3.4 Three-tier autonomy model

The system is autonomous within a declared operating envelope. Crossing that envelope is part of the design, not a failure.

| Tier | Name | Behavior | Examples |
|------|------|----------|----------|
| 1 | Executor autonomy | No protocol gate required | Reversible code changes, test writing, docs, refactoring |
| 2 | Council autonomy | Protocol approval required, no human | Spec creation, planning, build milestones, code review |
| 3 | Approval-gated | Council + human authorization | Deploys, migrations, security changes, dependency upgrades |

**Operational semantics:**

- **Classification scope:** Per-stage. Each stage is independently classified based on the files and actions it will touch.
- **Initial routing:** Static, rule-based, conservative. The governed system does not choose its own governance level.
- **Promotion:** Dynamic promotion only (Tier 1→2 or Tier 2→3). Never silent demotion.
- **Promotion stickiness:** Once a stage promotes to a higher tier, the promotion is sticky for the remainder of the autopilot run.
- **Evaluation unit:** The set of files the current stage intends to read/write, sourced from `SpecArtifact.target_files` and `PlanTask.target_files` at routing time, supplemented by runtime file-touch detection during execution.
- **Approval behavior:** When a stage hits Tier 3, the orchestrator continues preparation and analysis (building artifacts, running reviews) but blocks execution of external side effects until human approval via `autopilot_resume`.

**Static routing features (pre-execution, using declared intent):**
- Declared target files from `SpecArtifact.target_files` and `PlanTask.target_files` matching sensitive paths (auth/, migrations/, infra/, deploy/, permissions/)
- Dependency manifest changes (package.json, pyproject.toml, go.mod, etc.) listed in target_files
- Production config files listed in target_files
- External side effects declared in manifest (`side_effect_level`)
- Rollback difficulty (inferred from stage type and `side_effect_level`)
- Ambiguity in task description

**Dynamic promotion triggers (runtime, using observed behavior):**
- Newly touched sensitive files during execution (files not declared in target_files)
- `challenge` returns `not_ready`
- `review_loop` finds security or data-integrity findings with severity `critical` or `high`
- `decide` returns `deferred` or `experiment`
- Runtime detects irreversible action ahead (deploy, migration, publish)

### 3.5 Transparent gate injection

Workflow bodies stay single-agent in tone. The orchestrator injects protocol gates at artifact output boundaries. Workflows don't need to know about the two-agent model.

**Decision:** Workflows describe how to execute a stage well. The orchestrator handles when and how to gate transitions. This keeps workflow content cleaner and more reusable.

### 3.6 Structured manifests, not markdown parsing

The orchestrator must not parse arbitrary markdown structure as its control plane. Each workflow gets a sidecar manifest with explicit stage metadata.

**Decision:** Each workflow directory contains `manifest.yaml` (structured contract) + `workflow.md` (execution recipe). Artifact schemas live in Python/Pydantic, not markdown.

### 3.7 Work stages vs. gate stages

Work stages and gate stages are structurally different and must not be conflated.

**Decision:**
- **Work stages** execute a workflow recipe and produce a typed artifact (e.g., `plan` produces `PlanArtifact`). The orchestrating agent does the work.
- **Gate stages** invoke an AgentCouncil protocol and produce a transition decision. An independent agent evaluates. Gate stages use **existing protocol output types** — `ConsensusArtifact`, `ReviewArtifact`, `ConvergenceResult`, `ChallengeArtifact` — not new gate-specific types.
- The orchestrator normalizes protocol-specific outputs into a unified `GateDecision` (advance/revise/block) via a gate normalization layer.

### 3.8 Gate normalization layer

Different protocols return different artifact shapes. The orchestrator needs a uniform transition decision.

**Decision:** A `GateNormalizer` maps each protocol's output to a `GateDecision`:

| Protocol | Output Type | → advance | → revise | → block |
|----------|------------|-----------|----------|---------|
| `brainstorm` | `ConsensusArtifact` | `status == consensus \| consensus_with_reservations` | — | `status == unresolved_disagreement \| partial_failure` |
| `review` | `ReviewArtifact` | `verdict == pass` | `verdict == revise` | `verdict == escalate` |
| `review_loop` | `ConvergenceResult` | `final_verdict == pass` | `final_verdict == revise` | `final_verdict == escalate` |
| `challenge` | `ChallengeArtifact` | `readiness == ready` | `readiness == needs_hardening` | `readiness == not_ready` |
| `decide` | `DecideArtifact` | `outcome == decided` | `outcome == experiment` | `outcome == deferred` |

`GateDecision` is a simple enum: `advance`, `revise`, `block`. On `revise`, the orchestrator loops the work stage. On `block`, the orchestrator escalates (retry once with fallback backend, then pause for human).

### 3.9 Spec prep: research-first, low-friction, conditional council

The spec phase is the user's last high-bandwidth touchpoint. Every second of user time should buy maximum reduction in downstream block probability.

**Design principle:** Maximize autonomous executability per minute of user attention.

**Decision:** Add a `spec_prep` work stage before `plan` with three sub-steps:

**Sub-step 1: Codebase Research (autonomous, always for code tasks)**

Before asking the user anything, the system inspects the repo. This prevents generic questions.

Research identifies:
- Likely target files and directories
- Existing patterns and APIs to reuse
- Nearby tests and verification commands
- Sensitive paths that may promote autonomy tier
- Missing context that cannot be inferred
- Architectural options (only when real alternatives exist)
- **Verification environment** — test framework, docker-compose, dev server, service dependencies, Playwright config, required env vars/credentials
- **Delivery conventions** — branch strategy (from git history), PR templates, changelog files, version files, release scripts

Output: `CodebaseResearchBrief` — used to inform questions, not shown in full to the user. Consequential inferences (target files, assumptions, risk areas) are summarized for the user so they can correct bad repo interpretation.

**Sub-step 2: Spec Refinement (interactive, user engaged)**

Ask only blocking questions — those where a wrong assumption would cause rework, wrong user-visible behavior, safety risk, or tier promotion. Everything else becomes a documented assumption.

**Question budget:**
- Default: 0-3 blocking questions
- Hard max: 5
- Present assumptions alongside questions so user can correct silently

**Question priority (ordered by impact on autonomous execution):**
1. Acceptance criteria gaps — what does "done" look like? (stop condition)
2. Scope boundaries — what is explicitly out of scope?
3. Conflict resolution — existing code contradicts the request
4. Risk/approval boundaries — migrations, auth, deploys allowed?
5. Compatibility constraints — must existing behavior remain unchanged?
6. Verification environment — only when research can't determine test/service infrastructure (e.g., "No test setup found — how do you verify this works?" or "Integration tests need DB credentials — where are they?")
7. Delivery expectations — only when research can't determine branch/PR/release conventions (e.g., "Should this be a PR or direct commit?" or "Do you want a changelog entry?")
8. Decision preferences — when two approaches are valid, which tradeoff?
9. Priority guidance — correctness vs. speed, simplicity vs. configurability
10. Edge cases — what should happen when [specific scenario]?

**Note:** Categories 6 and 7 are only asked when codebase research fails to determine the answer. If research finds `docker-compose.yml`, don't ask "do you use Docker?" If git history shows PR-based workflow, don't ask about branch strategy.

**Sub-step 3: Architecture Review (conditional, council brainstorm)**

Run a council `brainstorm` only when triggered. Not every spec needs architecture review.

**Triggers (any one is sufficient):**
- Multiple viable implementation architectures
- Cross-module changes
- Public schema/API changes
- Security, auth, migrations, permissions, deployment, or dependency changes
- Low confidence in inferred target files
- Spec is minimal but blast radius appears large
- User explicitly requests architecture input

**Architecture review output feeds the spec, it does not replace it.** Produces: selected strategy, rejected alternatives, target module boundaries, key risks, assumptions to preserve.

**Handling minimal vs. detailed user input:**
- Detailed specs: validate fields, research target files, fill gaps, ask only if contradiction or high-risk ambiguity, skip architecture council unless triggers fire
- Minimal specs: infer as much as possible, draft spec with assumptions, ask up to 3 blocking questions, proceed only when assumptions are safe and reversible, otherwise pause

**Spec readiness check (before entering autonomous execution):**
- At least one requirement
- At least one testable acceptance criterion
- Clear non-goals or explicit "none known"
- Inferred or declared target files with confidence
- Known sensitive areas flagged
- Unresolved questions classified as blocking (asked) or assumptions (documented)
- **Verification feasibility:** Can we verify this autonomously? Test infrastructure identified or plan to generate probes. No unresolved credential/service blockers.
- **Delivery clarity:** Do we know how to package the result? Branch strategy, PR expectations, and release conventions are known or assumed.

If readiness fails, do not enter `plan`. Pause while the user is still present.

## 4. Protocol-to-Stage Mapping

Work stages and their default gate protocols:

| Work Stage | Input Artifact | Output Artifact | Gate Protocol | Gate Output Type | Why This Protocol |
|-----------|---------------|----------------|---------------|-----------------|-------------------|
| `spec_prep` | User intent / partial spec | `SpecPrepArtifact` | `none` (or conditional `brainstorm`) | — | Interactive with user; gate is the optional arch review within the stage |
| `plan` | `SpecPrepArtifact` | `PlanArtifact` | `review_loop` | `ConvergenceResult` | Plans need iterative critique — a bad plan poisons all downstream stages |
| `build` | `PlanArtifact` | `BuildArtifact` | `review_loop` | `ConvergenceResult` | Iterative code quality review with convergence |
| `verify` | `BuildArtifact` | `VerifyArtifact` | `challenge?` (conditional) | `ChallengeArtifact` | Stress-tests whether verified evidence is trustworthy — only fires for high-risk work |
| `ship` | `VerifyArtifact` | `ShipArtifact` | `none` | — | Deterministic readiness packaging — everything is already verified and challenged |

**Notes:**
- `spec_prep` is the only interactive stage — the user is engaged during research and questioning. After spec_prep completes, the user disengages.
- The `plan` stage consumes `SpecPrepArtifact` (not just `SpecArtifact`) so it has access to research findings, assumptions, architecture notes, and decision preferences.
- `plan` also includes `AcceptanceProbe` entries for each acceptance criterion — the plan designs *how* each criterion will be verified, not just *what* to build.
- `verify` has its own internal retry loop: verify fails → build fix → re-verify (max 3 loops, then escalate).
- `challenge` after verify is **conditional** — fires only for high-risk work (security, migrations, external side effects, Tier 3, or explicit user request). Normal Tier 2 work skips challenge.
- `ship` has **no gate** — it's deterministic assembly after everything is already verified and (optionally) challenged.
- `review_loop` is NOT a work stage — it is a gate-only protocol invoked after `plan` and `build`.
- `decide` is not used in MVP unless explicit competing options exist.

## 5. Artifact Schemas

All autopilot artifacts are Pydantic models in `agentcouncil/autopilot/artifacts.py`. They follow the same patterns as existing schemas in `agentcouncil/schemas.py` (typed fields, model validators for invariants, `Field(default_factory=list)` for lists).

### 5.1 SpecArtifact

The durable statement of what to build. Lean and focused — process metadata lives in `SpecPrepArtifact`.

```python
class SpecArtifact(BaseModel):
    spec_id: str                           # unique identifier (e.g., "spec-auth-migration")
    title: str                             # human-readable title
    objective: str                         # what this spec aims to achieve
    requirements: list[str]                # functional requirements (must-have)
    acceptance_criteria: list[str]         # testable conditions for completion
    constraints: list[str] = []            # technical or business constraints
    non_goals: list[str] = []              # explicitly out of scope
    context: Optional[str] = None          # background, motivation, prior decisions
    target_files: list[str] = []           # files/directories expected to be touched
    assumptions: list[str] = []            # non-blocking uncertainties documented as assumptions
    verification_hints: list[str] = []     # test commands, manual checks, or verification strategies
```

**Model invariants (self-contained, enforced by model_validator):**
- `requirements` must be non-empty
- `acceptance_criteria` must be non-empty
- `spec_id` must be non-empty and contain only `[a-z0-9-]`

### 5.2 CodebaseResearchBrief

Produced by spec_prep sub-step 1. Summarizes repo state relevant to the spec.

```python
class CodebaseResearchBrief(BaseModel):
    summary: str                           # one-paragraph overview of findings
    relevant_files: list[str] = []         # existing files related to the request
    existing_patterns: list[str] = []      # conventions, frameworks, patterns found
    likely_target_files: list[str] = []    # inferred files that will be modified
    test_commands: list[str] = []          # how to run relevant tests
    sensitive_areas: list[str] = []        # paths that may trigger tier promotion
    unknowns: list[str] = []              # things research could not determine
    confidence: Literal["high", "medium", "low"] = "medium"
    source_refs: list[SourceRef] = []      # files/locations examined
```

**Model invariants:**
- `summary` must be non-empty

### 5.3 ClarificationPlan

Produced by spec_prep sub-step 2. Separates blocking questions from assumptions.

```python
class ClarificationPlan(BaseModel):
    blocking_questions: list[str] = []     # questions asked to the user (max 5)
    user_answers: list[str] = []           # corresponding answers
    assumptions: list[str] = []            # non-blocking uncertainties, documented
    deferred_questions: list[str] = []     # questions saved for later if needed
```

**Model invariants:**
- `len(blocking_questions) <= 5`
- `len(user_answers) == len(blocking_questions)` (after refinement completes)

### 5.4 SpecPrepArtifact

The enriched launch packet for autonomous execution. Wraps a lean `SpecArtifact` with all the context the planner needs.

```python
class SpecPrepArtifact(BaseModel):
    prep_id: str                           # unique identifier
    finalized_spec: SpecArtifact           # the lean, durable spec

    # Research and clarification
    research: CodebaseResearchBrief
    clarification: ClarificationPlan

    # Advisory context (guidance, not requirements)
    architecture_notes: list[str] = []     # from optional arch review
    conventions_to_follow: list[str] = []  # "use pytest", "follow middleware pattern"
    decision_preferences: list[str] = []   # "prefer simplicity", "match existing patterns"
    priority_guidance: list[str] = []      # "correctness over speed"

    # Binding vs advisory distinction
    binding_decisions: list[str] = []      # user-confirmed, must be followed
    advisory_context: list[str] = []       # guidance, can be overridden with reason

    # Autonomy metadata
    recommended_tier: Literal[1, 2, 3] = 2
    escalation_triggers: list[str] = []    # conditions that should promote tier
```

**Model invariants:**
- `finalized_spec` must pass all `SpecArtifact` model invariants
- `prep_id` must be non-empty

**Semantic contract for downstream stages:**
- The `plan` stage **must** satisfy `finalized_spec` (requirements, acceptance_criteria, constraints, non_goals are binding)
- The `plan` stage **should** use research, architecture_notes, conventions, and preferences
- The `plan` stage **must not** treat `advisory_context` as binding unless also listed in `binding_decisions` or `finalized_spec`

### 5.5 PlanArtifact

Produced by the `plan` work stage. Decomposes the spec into ordered tasks.

```python
class PlanTask(BaseModel):
    task_id: str                           # unique within plan (e.g., "task-01")
    title: str
    description: str
    acceptance_criteria: list[str]         # testable conditions for this task
    depends_on: list[str] = []             # task_ids this depends on
    target_files: list[str] = []           # files this task will touch
    estimated_complexity: Literal["small", "medium", "large"] = "medium"

class AcceptanceProbe(BaseModel):
    probe_id: str                          # unique within plan
    criterion_id: str                      # format: "ac-{index}" zero-indexed into SpecArtifact.acceptance_criteria
    criterion_text: str                    # the acceptance criterion being verified
    verification_level: Literal["static", "unit", "integration", "smoke", "e2e"]
    target_behavior: str                   # what the probe checks
    command_hint: Optional[str] = None     # suggested verification command
    service_requirements: list[str] = []   # services needed (e.g., "postgres", "redis")
    expected_observation: str              # what success looks like
    mock_policy: Literal["allowed", "forbidden", "not_applicable"] = "forbidden"
    related_task_ids: list[str] = []       # which plan tasks implement this criterion
    confidence: Literal["high", "medium", "low"] = "medium"

class PlanArtifact(BaseModel):
    plan_id: str                           # unique identifier
    spec_id: str                           # links back to source spec
    prep_id: Optional[str] = None          # links back to spec prep (traceability)
    tasks: list[PlanTask]                  # ordered task breakdown
    execution_order: list[str]             # task_ids in execution sequence
    verification_strategy: str             # how completion will be verified
    acceptance_probes: list[AcceptanceProbe] = []  # HOW each criterion will be verified
```

**Model invariants (self-contained, enforced by model_validator):**
- `tasks` must be non-empty
- `execution_order` must contain exactly the task_ids from `tasks`
- All `depends_on` references must point to valid task_ids within the same plan
- All `AcceptanceProbe.related_task_ids` must reference valid task_ids

**Advisory invariant (enforced by planner agent, not model_validator):**
- Behavior-changing criteria should have at least one probe with `mock_policy == "forbidden"` and `verification_level in {"integration", "smoke", "e2e"}`. This requires semantic judgment about which criteria are "behavior-changing" and cannot be enforced by field inspection alone.

**Transition invariants (enforced by orchestrator at stage boundary):**
- `spec_id` must match the input `SpecArtifact.spec_id`
- Every `SpecArtifact.acceptance_criteria` item must map to at least one `AcceptanceProbe`

### 5.6 BuildArtifact

Produced by the `build` work stage. Contains implementation evidence.

```python
class BuildEvidence(BaseModel):
    task_id: str                           # which plan task this covers
    files_changed: list[str]               # paths modified
    test_results: Optional[str] = None     # test output summary
    verification_notes: str                # how this was verified

class BuildArtifact(BaseModel):
    build_id: str                          # unique identifier
    plan_id: str                           # links back to source plan
    spec_id: str                           # links back to source spec
    evidence: list[BuildEvidence]          # per-task implementation evidence
    all_tests_passing: bool                # overall test suite status
    files_changed: list[str]              # aggregate list of all files modified
    commit_shas: list[str] = []            # git commits produced
```

**Model invariants (self-contained, enforced by model_validator):**
- `evidence` must be non-empty

**Transition invariants (enforced by orchestrator at stage boundary):**
- Every `evidence[].task_id` must reference a valid task_id in the source `PlanArtifact`
- `plan_id` must match the input `PlanArtifact.plan_id`
- `spec_id` must match the input `SpecArtifact.spec_id`

### 5.7 VerificationEnvironment

Authoritative runtime environment discovered and validated by the verify stage.

```python
class VerificationEnvironment(BaseModel):
    project_types: list[str] = []          # ["python", "node", "frontend", "api", "cli"]
    test_commands: list[str] = []          # discovered test commands
    dev_server_command: Optional[str] = None
    service_commands: list[str] = []       # docker-compose up, etc.
    health_checks: list[str] = []          # endpoints/commands to confirm readiness
    required_env_vars: list[str] = []
    missing_env_vars: list[str] = []
    playwright_available: bool = False
    confidence: Literal["high", "medium", "low"] = "medium"
```

### 5.8 VerifyArtifact

Produced by the `verify` work stage. Proves the build works through executable evidence.

```python
class CommandEvidence(BaseModel):
    command: str
    cwd: str
    exit_code: int
    duration_seconds: float
    stdout_tail: str = ""                  # last N lines
    stderr_tail: str = ""                  # last N lines

class ServiceEvidence(BaseModel):
    name: str                              # "postgres", "redis", "dev-server"
    start_command: str
    health_check: Optional[str] = None
    port: Optional[int] = None
    status: Literal["started", "failed", "stopped"]
    logs_tail: str = ""

class CriterionVerification(BaseModel):
    criterion_id: str                      # format: "ac-{index}" zero-indexed, matching AcceptanceProbe.criterion_id
    criterion_text: str
    status: Literal["passed", "failed", "blocked", "skipped"]
    verification_level: Literal["static", "unit", "integration", "smoke", "e2e"]
    mock_policy: Literal["allowed", "forbidden", "not_applicable"]
    evidence_summary: str                  # human-readable explanation
    commands: list[CommandEvidence] = []    # exact commands run
    services: list[ServiceEvidence] = []   # services started for this check
    artifacts: list[str] = []              # screenshots, traces, logs
    failure_diagnosis: Optional[str] = None
    revision_guidance: Optional[str] = None  # actionable fix direction
    skip_reason: Optional[str] = None      # required when status == skipped
    blocker_type: Optional[str] = None     # required when status == blocked

class VerifyArtifact(BaseModel):
    verify_id: str
    build_id: str
    plan_id: str
    spec_id: str

    # Environment
    test_environment: VerificationEnvironment

    # Per-criterion evidence
    criteria_verdicts: list[CriterionVerification]

    # Aggregate results
    overall_status: Literal["passed", "failed", "blocked"]
    services_started: list[ServiceEvidence] = []
    generated_tests: list[str] = []        # tests created by verify (persistent or transient)
    coverage_gaps: list[str] = []          # areas without verification evidence

    # Retry guidance
    retry_recommendation: Literal["none", "retry_build", "retry_plan", "block"] = "none"
    revision_guidance: Optional[str] = None  # what to fix (for retry_build)
    failure_summary: Optional[str] = None
```

**Model invariants (self-contained, enforced by model_validator):**
- `overall_status == "passed"` requires all `criteria_verdicts` to have `status == "passed"` (no `failed`, `blocked`, or unjustified `skipped`)
- `status == "skipped"` requires non-empty `skip_reason`
- `status == "blocked"` requires non-empty `blocker_type`
- Behavior-changing criteria with `mock_policy == "forbidden"` must have real execution evidence (not mock-only)
- `retry_recommendation == "retry_build"` requires non-empty `revision_guidance`

**Transition invariants (enforced by orchestrator at stage boundary):**
- `build_id` must match the input `BuildArtifact.build_id`
- `spec_id` must match the input `SpecArtifact.spec_id`

**Verify → Build retry loop:**
- On `overall_status == "failed"`: orchestrator sends `revision_guidance` back to build stage (max 2 retries, hard cap 3)
- First retry: re-run failed checks + directly dependent checks
- Final retry: re-run full verification set
- After max retries: escalate to human (`paused_for_approval`)

### 5.9 ShipArtifact

Produced by the `ship` work stage. Deterministic readiness packaging — assembles verified evidence into an auditable delivery packet. MVP does NOT execute deploys.

```python
class ShipArtifact(BaseModel):
    ship_id: str                           # unique identifier
    verify_id: str                         # links back to verification proof
    build_id: str                          # links back to source build
    plan_id: str                           # links back to source plan
    spec_id: str                           # links back to source spec

    # Structured readiness facts
    branch_name: str                       # git branch
    head_sha: str                          # git commit SHA
    worktree_clean: bool                   # no unexpected changes
    tests_passing: bool                    # from VerifyArtifact
    acceptance_criteria_met: bool          # all criteria have passing evidence
    blockers: list[str] = []              # anything preventing ship

    # Human-facing content
    readiness_summary: str                 # overall readiness assessment
    release_notes: str                     # what changed, for humans
    rollback_plan: str                     # how to undo if something breaks
    remaining_risks: list[str] = []        # known risks accepted for shipping
    evidence_refs: list[str] = []          # pointers to verify evidence

    # Decision
    recommended_action: Literal["ship", "hold", "rollback"]
```

**Model invariants (self-contained, enforced by model_validator):**
- `recommended_action == "ship"` requires: no blockers, `tests_passing == True`, `acceptance_criteria_met == True`, `worktree_clean == True`, non-empty `rollback_plan`
- `recommended_action == "hold"` requires `remaining_risks` or `blockers` to be non-empty

**Transition invariants (enforced by orchestrator at stage boundary):**
- `verify_id` must match the input `VerifyArtifact.verify_id`
- `build_id` must match the input `BuildArtifact.build_id` (via VerifyArtifact)
- `spec_id` must match the input `SpecArtifact.spec_id`

### 5.10 GateDecision

Produced by the gate normalization layer. Uniform transition outcome.

```python
class GateDecision(BaseModel):
    decision: Literal["advance", "revise", "block"]
    protocol_type: Literal["brainstorm", "review", "review_loop", "challenge", "decide"]
    protocol_session_id: str               # reference to journal entry
    rationale: str                         # one-line reason
    revision_guidance: Optional[str] = None  # what to fix (when decision == revise)
```

### 5.11 Artifact Lineage

Every artifact carries `spec_id` to trace back to the originating spec. Each subsequent artifact also carries the ID of its immediate predecessor. This forms a chain: `SpecPrepArtifact → PlanArtifact → BuildArtifact → VerifyArtifact → ShipArtifact`.

- `SpecPrepArtifact` embeds the finalized `SpecArtifact` and carries `prep_id`
- `PlanArtifact` carries `spec_id` (from `finalized_spec.spec_id`) and optional `prep_id`
- `BuildArtifact` carries `spec_id` and `plan_id`
- `VerifyArtifact` carries `spec_id`, `plan_id`, and `build_id`
- `ShipArtifact` carries `spec_id`, `plan_id`, `build_id`, and `verify_id`

The `spec_id` is the durable delivery identity. The `prep_id` provides traceability to the exact research, assumptions, and decisions used during planning.

**Validation ownership:**
- **Model invariants** (self-contained field checks) are enforced by Pydantic `model_validator` on the artifact class itself. These require no external context.
- **Transition invariants** (cross-artifact lineage checks like `spec_id` matching) are enforced by the orchestrator at stage boundaries, where both the input and output artifacts are available. These are NOT in model validators.

## 6. Autopilot Run State

### 6.1 Storage

Autopilot runs are persisted to `~/.agentcouncil/autopilot/{run_id}.json`. This is separate from the protocol journal (`~/.agentcouncil/journal/`). Writes are atomic (temp file + rename), same as journal entries.

### 6.2 Run Schema

```python
class AutopilotRunStatus(str, Enum):
    running = "running"
    paused_for_approval = "paused_for_approval"
    paused_for_revision = "paused_for_revision"
    completed = "completed"
    failed = "failed"

class StageCheckpoint(BaseModel):
    stage_name: str
    status: Literal["pending", "in_progress", "gated", "advanced", "blocked", "skipped"]
    artifact_snapshot: Optional[dict] = None  # serialized stage output artifact
    gate_session_id: Optional[str] = None     # protocol journal reference
    gate_decision: Optional[str] = None       # advance/revise/block
    revision_guidance: Optional[str] = None   # what to fix (persisted from GateDecision when revise)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

class AutopilotRun(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    spec_id: str
    status: AutopilotRunStatus
    current_stage: str
    tier: int                                # current autonomy tier (1, 2, or 3)
    tier_promoted_at: Optional[str] = None   # stage name where promotion happened
    stages: list[StageCheckpoint]            # ordered stage checkpoints
    artifact_registry: dict[str, dict] = {}  # stage_name → serialized artifact
    child_session_ids: list[str] = []        # protocol journal session references
    started_at: float
    updated_at: float
    completed_at: Optional[float] = None
    failure_reason: Optional[str] = None
```

### 6.3 Resume Semantics

- `autopilot_resume(run_id)` loads the run state, finds the current stage, and continues from the last checkpoint.
- If `status == paused_for_approval`: resume executes the blocked stage after human approval.
- If `status == paused_for_revision`: resume re-executes the work stage using `StageCheckpoint.revision_guidance` (persisted from the gate's `GateDecision.revision_guidance`).
- If `status == failed`: resume is rejected with the failure reason.
- Resume reconstructs the artifact registry from persisted checkpoints — no in-memory state required.

### 6.4 Relationship to Protocol Journal

- Autopilot runs reference protocol sessions by `session_id` in `child_session_ids` and `StageCheckpoint.gate_session_id`.
- Protocol journals remain the source of truth for deliberation transcripts, findings, and consensus artifacts.
- Autopilot state is **never** duplicated into protocol journals. Each layer owns its own data.

## 7. Package Structure

```
agentcouncil/autopilot/
├── __init__.py
├── artifacts.py          # Pydantic artifact schemas (Section 5)
├── prep.py               # Spec prep: research, refinement, conditional arch review (Section 3.9)
├── run.py                # AutopilotRun, StageCheckpoint, persistence (Section 6)
├── loader.py             # Manifest schema + loader + stage registry
├── normalizer.py         # GateNormalizer: protocol outputs → GateDecision (Section 3.8)
├── orchestrator.py       # Linear stage state machine
├── verify.py             # Verify stage: infrastructure discovery, test execution, evidence collection
├── policy.py             # Gate policy, approval boundary, tier routing (Section 3.4)
├── workflows/
│   ├── spec_prep/
│   │   ├── manifest.yaml
│   │   └── workflow.md
│   ├── plan/
│   │   ├── manifest.yaml
│   │   └── workflow.md
│   ├── build/
│   │   ├── manifest.yaml
│   │   └── workflow.md
│   ├── verify/
│   │   ├── manifest.yaml
│   │   └── workflow.md
│   └── ship/
│       ├── manifest.yaml
│       └── workflow.md
```

### Manifest Schema

Each `manifest.yaml` declares:

```yaml
stage_name: plan
version: "1.0"
stage_type: work               # "work" or "gate" — gate stages are protocol-only
input_artifact: SpecPrepArtifact
output_artifact: PlanArtifact
default_gate: review_loop      # protocol to invoke after this work stage
side_effect_level: none        # none | local | external
retry_policy: once             # none | once | backend_fallback
approval_required: false
allowed_next:
  - build
source_provenance:
  repo: https://github.com/addyosmani/agent-skills
  path: skills/planning-and-task-breakdown/SKILL.md
  license: MIT
  commit: <sha>
  date_copied: 2026-04-XX
  modified: true
```

**Manifest fields:**
| Field | Required | Description |
|-------|----------|-------------|
| `stage_name` | yes | Unique stage identifier |
| `version` | yes | Manifest schema version |
| `stage_type` | yes | `work` (produces artifact) or `gate` (protocol-only) |
| `input_artifact` | yes | Pydantic model name for expected input (or `null` for first stage) |
| `output_artifact` | yes | Pydantic model name for stage output |
| `default_gate` | yes | Protocol to invoke: `brainstorm`, `review`, `review_loop`, `challenge`, `none`. For `challenge`, the policy layer may skip based on tier and risk classification (see [AP-25a]). |
| `side_effect_level` | yes | `none` (pure computation), `local` (file changes), `external` (deploy/publish) |
| `retry_policy` | yes | `none`, `once` (retry same backend), `backend_fallback` (retry with different backend) |
| `approval_required` | yes | Whether human approval is required regardless of tier |
| `allowed_next` | yes | List of valid next stage names |
| `source_provenance` | no | Attribution for copied content |

### MCP Surface (MVP)

Exposed through `server.py`:

| Tool | Purpose |
|------|---------|
| `autopilot_prepare(intent)` | Run spec_prep: research → questions → optional arch review → `SpecPrepArtifact` |
| `autopilot_start(prep)` | Begin autonomous execution from a `SpecPrepArtifact` |
| `autopilot_status(run_id)` | Check current stage, tier, progress, and any blocks |
| `autopilot_resume(run_id)` | Resume a paused or approval-blocked run |

**Note:** `autopilot_start` also accepts a raw `SpecArtifact` for backward compatibility — it wraps it in a minimal `SpecPrepArtifact` with empty research/clarification. The recommended path is `autopilot_prepare` → `autopilot_start`.

## 8. Workflow Copy Treatment

When copying from agent-skills:

**Keep:**
- Core process steps (the proven workflow spine)
- Red flags / failure modes
- Verification / completion checks

**Adapt:**
- Opening framing → reframe for autopilot stage context
- Verification → map to stage output artifact contract
- Tool/environment assumptions → generalize for AgentCouncil

**Drop:**
- "When to Use" (the router decides this)
- "Common Rationalizations" (human education, not execution)
- Slash command references
- Hook system references
- Interactive skill invocation patterns

**Expected survival rate:** ~40-60% of original content in recognizable form. Process spine preserved, wrapper rewritten.

**Attribution per copied file:**

```markdown
# Originally from: https://github.com/addyosmani/agent-skills
# Path: skills/planning-and-task-breakdown/SKILL.md
# License: MIT (Addy Osmani, 2025)
# Copied: 2026-04-XX, commit <sha>
# Modified for AgentCouncil autopilot integration
```

## 9. MVP Implementation Sequence

Ordered by dependency. Each phase produces testable artifacts with explicit acceptance criteria.

### Phase 1: Artifact Schemas

**Goal:** Define typed contracts that every other component depends on.

**Deliverable:** `agentcouncil/autopilot/artifacts.py`

**Acceptance criteria:**
- [AP-01] `SpecArtifact`, `CodebaseResearchBrief`, `ClarificationPlan`, `SpecPrepArtifact`, `PlanArtifact` (with `AcceptanceProbe`), `BuildArtifact`, `VerificationEnvironment`, `VerifyArtifact` (with `CriterionVerification`, `CommandEvidence`, `ServiceEvidence`), `ShipArtifact`, `GateDecision` are defined as Pydantic models with all fields from Section 5
- [AP-02] Each model has `model_validator` methods enforcing the **model invariants** (self-contained checks) listed in Section 5. Cross-artifact **transition invariants** are NOT in model validators — they are enforced by the orchestrator (Phase 5).
- [AP-03] All artifacts serialize to/from JSON without data loss
- [AP-04] Transition invariant helpers are defined (e.g., `validate_lineage(parent, child)`) but are standalone functions, not model validators. They accept both artifacts as arguments.
- [AP-05] Unit tests cover all invariant checks (valid and invalid inputs)

### Phase 2: Manifest Schema + Loader

**Goal:** Define stage contracts and build the discovery/validation layer.

**Deliverable:** `agentcouncil/autopilot/loader.py`

**Acceptance criteria:**
- [AP-06] Manifest YAML schema matches Section 7 exactly (all fields from the manifest table)
- [AP-07] Loader discovers workflow directories under `autopilot/workflows/`, parses `manifest.yaml`, validates required fields
- [AP-08] Loader validates that `input_artifact` and `output_artifact` reference known artifact model names from `artifacts.py`
- [AP-09] Loader validates `allowed_next` references point to existing stage names
- [AP-10] Stage registry maps stage names to parsed manifests + loaded workflow content
- [AP-11] Loader raises clear errors for missing fields, unknown artifact types, or circular `allowed_next` references

### Phase 3: Gate Normalization Layer

**Goal:** Uniform transition decisions from protocol-specific outputs.

**Deliverable:** `agentcouncil/autopilot/normalizer.py`

**Acceptance criteria:**
- [AP-12] `GateNormalizer` maps `ConsensusArtifact`, `ReviewArtifact`, `ConvergenceResult`, `ChallengeArtifact`, and `DecideArtifact` to `GateDecision` using the rules in Section 3.8
- [AP-13] Normalization is exhaustive — every valid protocol output produces a valid `GateDecision`
- [AP-14] Unknown or malformed protocol outputs produce `GateDecision(decision="block", rationale="...")`
- [AP-15] Unit tests cover all mapping rules from the table in Section 3.8

### Phase 4: Autopilot Run State + Persistence

**Goal:** Durable workflow state with checkpoint and resume.

**Deliverable:** `agentcouncil/autopilot/run.py`

**Acceptance criteria:**
- [AP-16] `AutopilotRun` and `StageCheckpoint` models match Section 6.2 exactly
- [AP-17] Runs persist to `~/.agentcouncil/autopilot/{run_id}.json` with atomic writes (temp + rename)
- [AP-18] Directory is created lazily on first write
- [AP-19] `AutopilotRun` status transitions follow: `running → paused_for_approval | paused_for_revision | completed | failed`
- [AP-20] Resume from `paused_for_approval` and `paused_for_revision` is supported; resume from `failed` is rejected
- [AP-21] Artifact registry is populated from `StageCheckpoint.artifact_snapshot` on resume (no in-memory state required)

### Phase 5: Linear Orchestrator Skeleton

**Goal:** Minimal state machine with typed artifact threading and manifest enforcement.

**Deliverable:** `agentcouncil/autopilot/orchestrator.py`

**Uses stub/test workflows for initial testing.** Real workflow content is added in Phase 6.

**Acceptance criteria:**
- [AP-22] Orchestrator loads stage manifests via loader, validates the linear path: `spec_prep → plan → build → verify → ship`
- [AP-23] At each work stage: validates incoming artifact type, executes stage (stub in Phase 5), validates output artifact type, enforces `allowed_next` constraint
- [AP-24] At each gate stage: invokes the manifest's `default_gate` protocol, normalizes output via `GateNormalizer`, produces `GateDecision`
- [AP-25] `advance` → proceed to next stage. `revise` → re-execute current work stage with `revision_guidance` (status: `paused_for_revision`). `block` → escalate to human (status: `paused_for_approval`). One unambiguous mapping per decision.
- [AP-25a] Conditional challenge: after verify, challenge gate fires when stage touches sensitive paths, `side_effect_level == external`, current tier == 3, or user explicitly requested challenge. Otherwise challenge is skipped and verify advances directly to ship.
- [AP-26] Orchestrator persists `AutopilotRun` state after each stage transition
- [AP-27] End-to-end test with stub workflows: `intent → spec_prep (stub) → plan (stub) → review_loop gate → build (stub) → review_loop gate → verify (stub) → challenge? gate → ship (stub) → completed`

### Phase 6: Copy + Adapt 3 Workflows + Spec Prep + Verify

**Goal:** Vendor real execution recipes and implement spec prep and verify logic.

**Deliverable:** `agentcouncil/autopilot/workflows/{spec_prep,plan,build,verify,ship}/`, `agentcouncil/autopilot/prep.py`, `agentcouncil/autopilot/verify.py`

**Acceptance criteria:**
- [AP-28] Copy from agent-skills: `planning-and-task-breakdown`, `incremental-implementation`, `shipping-and-launch`
- [AP-28a] `spec_prep` workflow is AgentCouncil-native (no upstream source — implements Section 3.9)
- [AP-28b] `prep.py` implements: codebase research (bounded, read-only), question generation with budget (0-3 default, 5 max), spec readiness check, conditional architecture council trigger
- [AP-28c] `prep.py` emits `SpecPrepArtifact` with `CodebaseResearchBrief`, `ClarificationPlan`, and populated `finalized_spec`
- [AP-28d] `verify` workflow is AgentCouncil-native (no upstream source — implements Section 5.8)
- [AP-28e] `verify.py` implements: infrastructure discovery and validation, five-level verification execution (static, unit, integration, smoke, e2e), per-criterion evidence collection with structured `CommandEvidence`/`ServiceEvidence`, service lifecycle management (start/health-check/teardown), verify→build retry loop (max 2, hard cap 3)
- [AP-28f] `verify.py` emits `VerifyArtifact` with per-criterion `CriterionVerification` and `retry_recommendation`
- [AP-28g] When project has no existing test infrastructure, verify generates minimal real integration/smoke probes from `AcceptanceProbe` entries
- [AP-28h] For frontend changes with Playwright available: browser automation exercises affected UI flows, captures screenshots + console errors + network traces
- [AP-29] Each copied file includes per-file attribution header (Section 8)
- [AP-30] `THIRD_PARTY_NOTICES.md` added at repo root with source provenance
- [AP-31] Editorial reduction per Section 8 (~40-60% survival)
- [AP-32] Each workflow has a valid `manifest.yaml` that passes loader validation
- [AP-33] End-to-end test with real workflows replaces stub test from Phase 5

### Phase 7: Approval Boundary

**Goal:** Minimal irreversible-action guard.

**Deliverable:** `agentcouncil/autopilot/policy.py` (partial)

**Acceptance criteria:**
- [AP-34] Stages with `side_effect_level: external` require human approval before execution
- [AP-35] Stages with `approval_required: true` in manifest always pause for approval
- [AP-36] Approval check runs before stage execution, not after
- [AP-37] Paused runs have `status: paused_for_approval` and resume via `autopilot_resume`
- [AP-38] Local workspace changes (`side_effect_level: local`) proceed without approval

### Phase 8: Rule-Based Router

**Goal:** Complexity routing with tier assignment.

**Deliverable:** `agentcouncil/autopilot/policy.py` (complete)

**Acceptance criteria:**
- [AP-39] Router classifies each stage into Tier 1, 2, or 3 based on declared intent (`SpecArtifact.target_files`, `PlanTask.target_files`, manifest `side_effect_level`, dependency files in target_files)
- [AP-40] Tier 1 stages skip protocol gates and execute directly
- [AP-41] Tier 2 stages use full autopilot pipeline with protocol gates
- [AP-42] Tier 3 stages require council deliberation + human sign-off
- [AP-43] Per-stage classification per Section 3.4 operational semantics
- [AP-44] Tier promotion is sticky for the remainder of the run

### Phase 9: Failure Handling + Dynamic Promotion

**Goal:** Resilience and safety refinement.

**Deliverable:** Updates to `orchestrator.py` and `policy.py`

**Acceptance criteria:**
- [AP-45] Protocol timeout: retry with `retry_policy` from manifest (once or backend_fallback)
- [AP-46] `GateDecision.block` after retry: pause run and escalate to human
- [AP-47] Dynamic tier promotion: auto-escalate when sensitive files detected mid-execution
- [AP-48] Partial completion: checkpoint at last successful stage, resume from there
- [AP-49] `AutopilotRun.failure_reason` populated on failure for diagnostic clarity

### Post-MVP Additions

After the core autopilot works end-to-end:

- **debug** stage (from debugging workflow) — failure recovery within build
- **harden** stage (from security workflow) — Tier 3 security-sensitive work
- `decide` protocol integration — when explicit competing options exist
- Multi-backend gate execution — different protocols on different backends
- Run-level search (FTS5 over autopilot runs)
- Full vision-to-spec ingestion (`autopilot_prepare` accepts a multi-page vision file and produces a complete `SpecPrepArtifact`)
- Delegation model with scoped task assignment, ownership boundaries, and return paths

## 10. Relation to VISION.md

Autopilot MVP is the **first slice** of capability #12 from VISION.md. It covers a linear pipeline with council gates — not the full Autopilot vision.

| VISION.md Capability | MVP Coverage | Status |
|---------------------|-------------|--------|
| 5. Decompose | `plan` work stage produces `PlanArtifact` | Covered |
| 6. Delegate | Not covered — orchestrator assigns stages, but no scoped delegation model | **Post-MVP** |
| 7. Execute | `build` work stage executes implementation | Covered |
| 8. Verify | `verify` work stage with five-level testing + per-criterion evidence | **Covered** |
| 9. Reconvene | Gate protocols at transitions serve as reconvene points | Covered |
| 10. Memory | Autopilot run state + journal references | **Partial** (persistence only, no cross-run memory) |
| 12. Autopilot | Linear pipeline with council gates and approval boundaries | **First slice** |

**Positioning:** AgentCouncil remains the deliberation substrate. `agentcouncil/autopilot/` becomes the autonomous workflow layer. This is the first concrete implementation path toward the full Autopilot vision.

### MVP Non-Goals (explicitly deferred)

- Full vision-to-spec ingestion from a vision file (MVP `spec_prep` handles rough descriptions but not multi-page vision documents)
- Delegation model with scoped assignment, ownership, boundaries, return paths
- Cross-run memory (prior autopilot decisions informing new runs)
- Branching/parallel stage execution (MVP is linear only)
- `decide` protocol as a default gate (only on-demand when competing options exist)

## 11. What Autopilot Is NOT

- Not a YAML pipeline runner (the orchestrator manages typed artifacts and protocol gates, not script execution)
- Not a replacement for AgentCouncil's protocols (protocols remain the governance primitives; autopilot sequences them)
- Not fully unsupervised for all tasks (Tier 3 requires human approval for irreversible actions)
- Not a fork of agent-skills (we copy execution recipes, not the project structure or philosophy)
- Not a generic task automation framework (it's purpose-built for council-governed software delivery)
- Not the full VISION.md Autopilot capability (MVP is the first slice — linear pipeline with gates)

## 12. Open Risks

1. **Latency** — Each protocol gate adds 30-120 seconds. A 3-stage pipeline with gates could take 5-10 minutes. Routing must be aggressive.
2. **Artifact schema design** — Weak contracts make recipe import and stage threading brittle. Draft schemas in Section 5 mitigate but may need revision.
3. **Static routing gaps** — Rule-based routing may miss subtle risk signals until dynamic promotion is tuned with real usage data.
4. **Recipe adaptation effort** — Vendored skills may need substantial editing to fit the typed artifact model. Budget ~40-60% survival rate.
5. **Workflow-level persistence** — Adds complexity beyond protocol-level journaling. Must stay referential, not duplicative.
6. **Over-deliberation** — Challenge is expensive and can introduce adversarial noise if applied too broadly. Keep it scarce.
7. **Approval boundary UX** — Must be designed so the system remains useful while respecting external side-effect limits.
8. **Gate normalization edge cases** — Protocol outputs may not always map cleanly to advance/revise/block. The `block` fallback for unknown outputs is conservative but may over-block.
9. **Integration test infrastructure** — Starting databases, containers, and dev servers autonomously may require credentials, ports, or tools that aren't available. Verify must handle gracefully.
10. **Generated test flakiness** — Auto-generated integration probes may be flaky without state isolation, timing control, and cleanup. False failures waste retry budget.
11. **Service teardown** — Repeated verify retries could leave orphaned processes, ports, or containers if teardown isn't robust.
12. **Pre-existing test failures** — Distinguishing failures caused by the build from pre-existing failures is hard without a clean baseline.

---

*Generated from four AgentCouncil brainstorm sessions + two review loops (2026-04-15). Consensus between Claude and Codex.*
