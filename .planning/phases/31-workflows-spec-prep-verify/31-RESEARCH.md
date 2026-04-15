# Phase 31: Workflows + Spec Prep + Verify - Research

**Researched:** 2026-04-15
**Domain:** Python autopilot workflow content, spec prep logic, verify execution engine
**Confidence:** HIGH

## Summary

Phase 31 is the largest phase in the autopilot roadmap (17 requirements). It transitions five workflow directories from placeholder stubs to real execution content, implements `prep.py` (the spec_prep stage runner), and implements `verify.py` (the verify stage runner). The orchestrator is complete and tested with stubs; this phase replaces those stubs with working implementations.

The three vendored workflows (plan, build, ship) are editorial adaptations of agent-skills SKILL.md files copied with MIT attribution headers. The two AgentCouncil-native workflows (spec_prep, verify) are written from scratch but draw on AUTOPILOT-ROADMAP.md sections 3.9 and 5.8 respectively. The ship stage also produces a `ShipArtifact` completing PERS-03.

The key integrations to understand are: (1) how runners plug into `LinearOrchestrator` via the `StageRunner` callable, (2) how manifest `source_provenance` fields work in `StageManifest`, and (3) how the verify→build retry loop signals back through `VerifyArtifact.retry_recommendation` and `revision_guidance`.

**Primary recommendation:** Build prep.py and verify.py as stage runner modules, update the five workflow.md files with real content, add source_provenance to the three vendored manifests, and add THIRD_PARTY_NOTICES.md at repo root. The end-to-end test already exists in `test_autopilot_orchestrator.py::TestEndToEnd` — extend it to assert non-empty workflow_content for all five stages after the placeholder workflow.md files are replaced.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting. Use ROADMAP phase goal, success criteria, and codebase conventions to guide decisions.

### Claude's Discretion
All implementation choices.

### Deferred Ideas (OUT OF SCOPE)
None — discuss phase skipped.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PREP-01 | Codebase research identifies target files, existing patterns, test infrastructure, sensitive areas, verification environment | `prep.py` run_codebase_research() producing CodebaseResearchBrief; uses pathlib/subprocess to walk repo and detect test frameworks |
| PREP-02 | Interactive spec refinement asks 0-3 blocking questions with 5 hard max, presents full understanding with assumptions | `prep.py` run_spec_refinement() with ClarificationPlan; budget enforced via ClarificationPlan.blocking_questions max-5 validator |
| PREP-03 | Conditional architecture council brainstorm triggers for cross-module, schema/API, security, or ambiguous work | `prep.py` should_trigger_architecture_council() → calls brainstorm protocol when condition met; result feeds SpecPrepArtifact.architecture_notes |
| PREP-04 | Spec readiness check validates requirements, acceptance criteria, verification feasibility, and delivery clarity before autonomous execution | `prep.py` check_spec_readiness() → raises or returns; called after refinement, before returning SpecPrepArtifact |
| PREP-05 | SpecPrepArtifact distinguishes binding decisions from advisory context | Already in artifacts.py: SpecPrepArtifact.binding_decisions vs .advisory_context fields exist |
| VER-01 | Five verification levels: static, unit, integration, smoke, e2e | `verify.py` with a dispatch table per AcceptanceProbe.verification_level; already typed in CriterionVerification.verification_level |
| VER-02 | Real integration testing — start services, hit real endpoints, check real state (no mocks at integration/e2e level) | `verify.py` service lifecycle manager: start, health-check, teardown; CommandEvidence captures real exit codes |
| VER-03 | Per-acceptance-criterion evidence with structured command results, service lifecycle, and artifacts | `verify.py` produces one CriterionVerification per AcceptanceProbe in PlanArtifact.acceptance_probes |
| VER-04 | Verify → build retry loop with actionable failure evidence (max 2 retries, hard cap 3) | Orchestrator already has max_revise_iterations=3; verify.py sets retry_recommendation='retry_build' + revision_guidance when failed; orchestrator re-runs build runner with guidance |
| VER-05 | Generated integration probes when project has no existing test infrastructure | `verify.py` probe_generator: when test_commands is empty, generate minimal pytest file from AcceptanceProbe entries |
| VER-06 | Playwright/browser automation for frontend changes | `verify.py` conditionally runs Playwright when VerificationEnvironment.playwright_available=True and verification_level='e2e' |
| WORK-01 | Vendored agent-skills workflows (plan, build, ship) with MIT attribution and editorial adaptation | workflow.md for plan/build/ship adapted from agent-skills; manifest.yaml gains source_provenance block |
| WORK-02 | AgentCouncil-native spec_prep workflow implementing research-first questioning | spec_prep/workflow.md written from scratch per Section 3.9 of AUTOPILOT-ROADMAP.md |
| WORK-03 | AgentCouncil-native verify workflow implementing 5-level testing pyramid | verify/workflow.md written from scratch per Section 5.8 of AUTOPILOT-ROADMAP.md |
| WORK-04 | Agent-skills repo used as standing reference throughout all phases | Fetch current content from https://github.com/addyosmani/agent-skills before writing any workflow |
| PERS-03 | Ship produces structured readiness packet with branch/SHA, verification status, release notes, rollback plan | ship stage runner produces ShipArtifact with all required fields; ShipArtifact model already defined |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.x (already used) | Artifact validation | All autopilot artifacts already use Pydantic v2 |
| subprocess | stdlib | Command execution in verify.py | Real test execution requires subprocess; no dependency needed |
| pathlib | stdlib | Codebase file discovery in prep.py | Already used throughout codebase |
| asyncio | stdlib | Potential async stage execution (noted in server.py Phase 31 TODO) | MCP server is already FastMCP-based |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| playwright | optional | Browser automation for VER-06 | Only when VerificationEnvironment.playwright_available=True |
| PyYAML | already used | manifest.yaml reads | Already dependency (used by loader.py) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| subprocess for command execution | asyncio subprocess | async subprocess would match server.py TODO but adds complexity; Phase 31 can use sync subprocess with explicit timeout |
| Inline verify logic | External test runner wrapper | Inline subprocess keeps dependency surface minimal |

## Architecture Patterns

### Recommended Project Structure
```
agentcouncil/autopilot/
├── prep.py               # NEW: spec_prep stage runner (PREP-01..05)
├── verify.py             # NEW: verify stage runner (VER-01..06)
├── workflows/
│   ├── spec_prep/
│   │   ├── manifest.yaml   # EXISTS: no source_provenance (native)
│   │   └── workflow.md     # UPDATE: placeholder → real content
│   ├── plan/
│   │   ├── manifest.yaml   # UPDATE: add source_provenance for agent-skills
│   │   └── workflow.md     # UPDATE: placeholder → adapted agent-skills content
│   ├── build/
│   │   ├── manifest.yaml   # UPDATE: add source_provenance for agent-skills
│   │   └── workflow.md     # UPDATE: placeholder → adapted agent-skills content
│   ├── verify/
│   │   ├── manifest.yaml   # EXISTS: no source_provenance (native)
│   │   └── workflow.md     # UPDATE: placeholder → real content
│   └── ship/
│       ├── manifest.yaml   # UPDATE: add source_provenance for agent-skills
│       └── workflow.md     # UPDATE: placeholder → adapted agent-skills content
THIRD_PARTY_NOTICES.md       # NEW: at repo root
```

### Pattern 1: StageRunner Callable Interface
**What:** Each stage (spec_prep, verify, ship) must match the `StageRunner` type alias in orchestrator.py.
**When to use:** For all real stage implementations.
**Example:**
```python
# From orchestrator.py:
StageRunner = Callable[[AutopilotRun, dict[str, Any], Optional[str]], Any]

# prep.py exposes a function matching this signature:
def run_spec_prep(run: AutopilotRun, registry: dict[str, Any], guidance: Optional[str] = None) -> SpecPrepArtifact:
    ...

# verify.py exposes:
def run_verify(run: AutopilotRun, registry: dict[str, Any], guidance: Optional[str] = None) -> VerifyArtifact:
    ...
```

The orchestrator wires these via `runners={"spec_prep": run_spec_prep, "verify": run_verify, "ship": run_ship}` in `autopilot_start_tool`.

### Pattern 2: SourceProvenance in Manifest
**What:** Manifests for vendored workflows must add a `source_provenance` block.
**When to use:** For plan, build, ship workflows copied from agent-skills.
**Example:**
```yaml
# plan/manifest.yaml — add this block:
source_provenance:
  repo: https://github.com/addyosmani/agent-skills
  path: skills/planning-and-task-breakdown/SKILL.md
  license: MIT
  commit: bf2fa6994407c9c888fc19a03fd54957991cfa0e
  date_copied: 2026-04-15
  modified: true
```
The `SourceProvenance` Pydantic model in loader.py already supports this optional field.

### Pattern 3: Attribution Header for workflow.md
**What:** Each copied workflow.md must start with an attribution comment block.
**When to use:** plan, build, ship workflow.md files.
**Example:**
```markdown
<!--
Originally from: https://github.com/addyosmani/agent-skills
Path: skills/planning-and-task-breakdown/SKILL.md
License: MIT (Addy Osmani, 2025)
Copied: 2026-04-15, commit bf2fa6994407c9c888fc19a03fd54957991cfa0e
Modified for AgentCouncil autopilot integration
-->
```

### Pattern 4: Verify → Build Retry Loop
**What:** When verify fails, set `retry_recommendation='retry_build'` and `revision_guidance` on the VerifyArtifact. The orchestrator's `_run_stage_with_gate` handles re-running the build runner with that guidance.
**When to use:** In verify.py when overall_status == "failed".

The orchestrator already implements max_revise_iterations=3, but the verify stage uses `default_gate=challenge` (or none for tier=2). The verify→build retry loop is therefore an orchestrator-internal re-run of the BUILD stage, triggered when verify emits `retry_recommendation='retry_build'`.

**Critical clarification:** The "retry loop fires at most twice before escalating to paused_for_approval" (success criterion #3) means the build stage re-runs max 2 times after initial failure. The orchestrator already has max_revise_iterations=3 which means: 1 initial run + 2 revises = 3 total attempts. This is already wired. The verify runner just needs to set the right retry_recommendation.

### Pattern 5: Prep.py Structure
**What:** Three sub-steps from AUTOPILOT-ROADMAP.md Section 3.9.
```python
def run_spec_prep(run: AutopilotRun, registry: dict, guidance: Optional[str]) -> SpecPrepArtifact:
    spec = _extract_spec_from_run(run)           # from run.artifact_registry or spec_id lookup
    brief = run_codebase_research(spec)          # Sub-step 1: autonomous file inspection
    clarification = run_spec_refinement(spec, brief)  # Sub-step 2: 0-3 questions (interactive or auto-skip)
    arch_notes = run_arch_council_if_needed(spec, brief)  # Sub-step 3: conditional brainstorm
    check_spec_readiness(spec, brief, clarification)  # Gate check — raises if not ready
    return SpecPrepArtifact(
        prep_id=f"prep-{uuid4().hex[:8]}",
        finalized_spec=spec,
        research=brief,
        clarification=clarification,
        architecture_notes=arch_notes,
        binding_decisions=[...],
        advisory_context=[...],
    )
```

### Pattern 6: Verify.py Structure
**What:** Infrastructure discovery → five-level execution → per-criterion evidence collection.
```python
def run_verify(run: AutopilotRun, registry: dict, guidance: Optional[str]) -> VerifyArtifact:
    plan_art = registry.get("plan")  # AcceptanceProbe entries
    build_art = registry.get("build")
    env = discover_verification_environment(run)  # detects test commands, services, playwright
    verdicts = []
    for probe in plan_art.acceptance_probes:
        verdict = execute_criterion(probe, env)  # dispatches by verification_level
        verdicts.append(verdict)
    overall = "passed" if all(v.status == "passed" for v in verdicts) else "failed"
    guidance_out = _build_revision_guidance(verdicts) if overall == "failed" else None
    return VerifyArtifact(
        verify_id=f"verify-{uuid4().hex[:8]}",
        build_id=build_art.build_id,
        plan_id=plan_art.plan_id,
        spec_id=run.spec_id,
        test_environment=env,
        criteria_verdicts=verdicts,
        overall_status=overall,
        retry_recommendation="retry_build" if overall == "failed" else "none",
        revision_guidance=guidance_out,
    )
```

### Pattern 7: Ship Stage Runner
**What:** Deterministic readiness packaging using VerifyArtifact and BuildArtifact from registry.
```python
def run_ship(run: AutopilotRun, registry: dict, guidance: Optional[str]) -> ShipArtifact:
    verify_art = registry["verify"]
    build_art = registry["build"]
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode()
    branch = subprocess.check_output(["git", "branch", "--show-current"]).strip().decode()
    return ShipArtifact(
        ship_id=f"ship-{uuid4().hex[:8]}",
        verify_id=verify_art.verify_id,
        build_id=build_art.build_id,
        plan_id=registry["plan"].plan_id,
        spec_id=run.spec_id,
        branch_name=branch,
        head_sha=head_sha,
        worktree_clean=_check_worktree_clean(),
        tests_passing=verify_art.overall_status == "passed",
        acceptance_criteria_met=verify_art.overall_status == "passed",
        readiness_summary=_build_readiness_summary(verify_art),
        release_notes=_build_release_notes(build_art),
        rollback_plan=f"git revert {head_sha}",
        recommended_action="ship" if verify_art.overall_status == "passed" else "hold",
        remaining_risks=verify_art.coverage_gaps,
    )
```

### Anti-Patterns to Avoid
- **Monolithic runner:** Don't put all spec_prep logic inline in a lambda — use prep.py as a proper module with testable sub-functions
- **Mocking at integration level:** VER-02 explicitly forbids mock substitution at integration/e2e level; real subprocess.run calls with timeout
- **Asking questions in automated context:** prep.py sub-step 2 must handle the case where there's no interactive user — auto-proceed with documented assumptions rather than blocking
- **Mutating run object directly in runners:** Runners receive run for context (spec_id, tier) but should not mutate it — the orchestrator owns state transitions

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service health polling | Custom backoff loop | subprocess.run with timeout + retries using existing pattern | Already enough for MVP; over-engineering before real service needs emerge |
| Playwright wrapper | Custom browser client | `playwright` Python library if available (already handled by VerificationEnvironment.playwright_available flag) | Official library handles CDP, contexts, and screenshot capture |
| Codebase file walker | Custom recursion | `pathlib.Path.rglob()` + gitignore filtering | Already used throughout the codebase |
| Test framework detection | Ad-hoc string matching | Check for `pyproject.toml [tool.pytest]`, `package.json scripts.test`, `Makefile` test targets | Standard detection patterns used by all CI tools |

**Key insight:** The artifact contracts are already complete. Phase 31 is about filling in real implementations that produce those artifacts — don't redesign the data shapes.

## Common Pitfalls

### Pitfall 1: Blocking on Interactive Input in prep.py Sub-Step 2
**What goes wrong:** prep.py calls `input()` or equivalent to ask the user questions. In `autopilot_start` context the runner is called programmatically with no terminal attached — the call hangs or raises.
**Why it happens:** The spec says "interactive spec refinement" but the Stage 30 orchestrator calls runners as plain callables.
**How to avoid:** Phase 31 scope is the automated path — run with documented assumptions when in autonomous execution. The interactive flow (asking real questions) is an MCP tool concern that maps to `autopilot_prepare` being called from a Claude session. Design prep.py to be callable in both modes via a `interactive: bool` parameter or by checking if the spec already has clarification data from the registry.
**Warning signs:** Test hangs on `test_autopilot_orchestrator.py::TestMCPTools::test_start_completes_run`.

### Pitfall 2: Verify Loop Wired Through Wrong Gate
**What goes wrong:** Implementing the verify→build retry loop inside verify.py by calling the build runner directly, bypassing the orchestrator's revise mechanism.
**Why it happens:** VER-04 describes a "retry loop" which sounds like an internal loop.
**How to avoid:** The orchestrator already handles revise loops (max_revise_iterations=3). Verify.py should just set `retry_recommendation='retry_build'` and `revision_guidance` on the VerifyArtifact. The gate for the verify stage is `challenge` or `none` (for tier=2). But the verify→build retry is a separate concern: it requires the orchestrator to re-run the BUILD stage, not re-run verify. This means the orchestrator needs to know that a failed VerifyArtifact should cause build to re-run. **This is new orchestrator behavior not yet implemented.** See Open Questions.
**Warning signs:** Success criterion #3 says "orchestrator sends revision_guidance back to build stage and re-runs" — the orchestrator must detect this case.

### Pitfall 3: workflow.md Content Too Thin to Pass loader Test
**What goes wrong:** `test_default_registry_has_workflow_content` asserts all five stages have non-empty workflow_content. Currently all five are placeholders (5 words each). The test passes now but will still pass after Phase 31 since any non-empty content passes. However the end-to-end Phase 31 success criterion says "end-to-end test from Phase 30 passes with real workflow content replacing stubs" — this means a NEW assertion checking meaningful content length or specific section headers is needed.
**How to avoid:** Plan a new test `test_default_registry_workflow_content_is_real` that checks content length > 500 chars or contains a specific header like "## Process" or "## Steps".

### Pitfall 4: manifest.yaml Validation Failure After Adding source_provenance
**What goes wrong:** Adding source_provenance to plan/build/ship manifests breaks the manifest loader if the YAML structure doesn't match `SourceProvenance` field names exactly.
**How to avoid:** The `SourceProvenance` model in loader.py requires: `repo`, `path`, `license`, `commit`, `date_copied`, `modified` (default False). Use exactly these field names in YAML.

### Pitfall 5: ShipArtifact Invariant Violations
**What goes wrong:** ship runner sets `recommended_action='ship'` but `worktree_clean=False` or `blockers` is non-empty, causing Pydantic to raise.
**How to avoid:** The ShipArtifact model_validator enforces: `recommended_action='ship'` requires `blockers=[]`, `tests_passing=True`, `acceptance_criteria_met=True`, `worktree_clean=True`, non-empty `rollback_plan`. Use `recommended_action='hold'` when verification status is not 'passed'.

### Pitfall 6: Missing prep_id Generation
**What goes wrong:** SpecPrepArtifact requires non-empty `prep_id` (validated by model_validator). The stub uses "prep-stub" but the real runner must generate unique IDs.
**How to avoid:** Use `f"prep-{uuid.uuid4().hex[:8]}"` consistent with `run-{uuid}` pattern in server.py.

## Code Examples

### Correct StageRunner Registration in server.py (autopilot_start_tool)
```python
# Source: agentcouncil/server.py lines 1197-1210
# Current (Phase 30 stub):
orchestrator = LinearOrchestrator(registry=registry, runners={})

# Phase 31 update:
from agentcouncil.autopilot.prep import run_spec_prep
from agentcouncil.autopilot.verify import run_verify
from agentcouncil.autopilot.ship import run_ship  # or inline in verify.py
orchestrator = LinearOrchestrator(
    registry=registry,
    runners={"spec_prep": run_spec_prep, "verify": run_verify, "ship": run_ship},
)
```

### CodebaseResearchBrief Population (prep.py)
```python
# Source: artifacts.py CodebaseResearchBrief definition
brief = CodebaseResearchBrief(
    summary="Python project using pytest. 3 target files identified.",
    relevant_files=list(Path(".").rglob("*.py"))[:20],
    test_commands=["python3 -m pytest tests/ -x -q"],
    sensitive_areas=[],
    confidence="high",
)
```

### CommandEvidence from subprocess (verify.py)
```python
import subprocess, time
def run_command(cmd: str, cwd: str, timeout: int = 60) -> CommandEvidence:
    t0 = time.monotonic()
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                            text=True, timeout=timeout)
    return CommandEvidence(
        command=cmd, cwd=cwd, exit_code=result.returncode,
        duration_seconds=time.monotonic() - t0,
        stdout_tail=result.stdout[-2000:],
        stderr_tail=result.stderr[-2000:],
    )
```

### THIRD_PARTY_NOTICES.md Format
```markdown
# Third-Party Notices

## agent-skills

- Repository: https://github.com/addyosmani/agent-skills
- License: MIT
- Copyright: Addy Osmani, 2025
- Commit: bf2fa6994407c9c888fc19a03fd54957991cfa0e
- Date copied: 2026-04-15

Files derived from this source:
- agentcouncil/autopilot/workflows/plan/workflow.md
- agentcouncil/autopilot/workflows/build/workflow.md
- agentcouncil/autopilot/workflows/ship/workflow.md
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Stub runners in orchestrator.py | Real prep.py + verify.py runners | Phase 31 | All five stages produce real artifacts |
| Placeholder workflow.md (5 words) | Real editorial adaptations of agent-skills | Phase 31 | Loader test `test_default_registry_has_workflow_content` has meaningful content |
| No attribution | MIT headers + THIRD_PARTY_NOTICES.md | Phase 31 | WORK-01 requirement satisfied |

**Deprecated/outdated:**
- The `_stub_spec_prep_artifact()`, `_stub_plan_artifact()` etc. in orchestrator.py are intentionally NOT removed — they remain as internal fallbacks when runners dict has no entry. The real runners replace them by being registered in server.py, not by modifying orchestrator.py.

## Open Questions

1. **Verify → Build Retry Loop Orchestrator Wiring**
   - What we know: The success criterion says "orchestrator sends revision_guidance back to build stage and re-runs." The orchestrator already re-runs a stage when a gate returns `revise`. But verify's gate is `challenge` (or `none` for tier=2). The verify→build retry is cross-stage, not same-stage revise.
   - What's unclear: How does a failed VerifyArtifact cause the BUILD stage to re-run? The current LinearOrchestrator only re-runs the current stage on `revise`. It does NOT backtrack to a previous stage.
   - Recommendation: Phase 31 must add a post-verify check in `_run_stage_with_gate` or `run_pipeline`: after verify produces a VerifyArtifact, if `retry_recommendation == 'retry_build'`, back up current_stage to "build" and re-run with `revision_guidance`. This is new orchestrator logic, likely a small addition to `run_pipeline` before advancing to the next stage.

2. **Interactive vs Autonomous Mode for prep.py**
   - What we know: The Phase 31 success criterion says "at most 3 blocking questions asked of the user before the spec readiness check passes." This implies the runner CAN ask questions.
   - What's unclear: In the context of `autopilot_start_tool` (programmatic call from test), there's no channel to ask questions. The MCP surface comment in server.py says "Phase 31 must convert this to async."
   - Recommendation: For Phase 31, implement prep.py with a `question_budget` param where in test/programmatic context it defaults to 0 (document all as assumptions). The success criterion's "at most 3" refers to the interactive path through `autopilot_prepare_tool`. Accept this duality: `autopilot_prepare` is the interactive path (asking questions), `autopilot_start` is the autonomous path (assumptions only).

3. **Playwright Availability Detection**
   - What we know: VER-06 requires browser automation when Playwright is available. `VerificationEnvironment.playwright_available` tracks this.
   - What's unclear: How to detect Playwright in the target repo — check `package.json` devDependencies? Check if `playwright` Python package is installed? Both?
   - Recommendation: In `discover_verification_environment()`, set `playwright_available=True` if `importlib.util.find_spec('playwright')` succeeds OR if `package.json` contains `@playwright/test`. Guard all Playwright calls with this flag.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| python3 | Test execution | ✓ | 3.14 | — |
| pytest | Test suite | ✓ | (installed in venv) | — |
| subprocess (stdlib) | verify.py command execution | ✓ | stdlib | — |
| pathlib (stdlib) | prep.py file discovery | ✓ | stdlib | — |
| playwright (Python) | VER-06 browser automation | ? | unknown | Skip VER-06 path if unavailable |
| git | ship runner HEAD SHA | ✓ | (system git) | Use "unknown" if git unavailable |

**Missing dependencies with no fallback:** None that block Phase 31.
**Missing dependencies with fallback:** playwright — entire VER-06 code path is conditional on `VerificationEnvironment.playwright_available`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already configured) |
| Config file | pyproject.toml |
| Quick run command | `python3 -m pytest tests/test_autopilot_orchestrator.py tests/test_autopilot_loader.py -x -q` |
| Full suite command | `python3 -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PREP-01 | CodebaseResearchBrief populated with relevant_files, test_commands | unit | `pytest tests/test_autopilot_prep.py::test_codebase_research_populates_brief -x` | ❌ Wave 0 |
| PREP-02 | ClarificationPlan has ≤3 blocking_questions | unit | `pytest tests/test_autopilot_prep.py::test_clarification_budget -x` | ❌ Wave 0 |
| PREP-03 | Architecture council triggered by cross-module spec | unit | `pytest tests/test_autopilot_prep.py::test_arch_council_trigger -x` | ❌ Wave 0 |
| PREP-04 | Spec readiness check raises when no acceptance criteria | unit | `pytest tests/test_autopilot_prep.py::test_readiness_check_rejects_empty -x` | ❌ Wave 0 |
| PREP-05 | SpecPrepArtifact has binding_decisions separate from advisory_context | unit | `pytest tests/test_autopilot_prep.py::test_prep_artifact_fields -x` | ❌ Wave 0 |
| VER-01 | All five verification levels execute different logic | unit | `pytest tests/test_autopilot_verify.py::test_verification_levels -x` | ❌ Wave 0 |
| VER-02 | CommandEvidence has real exit code (not mocked) | integration | `pytest tests/test_autopilot_verify.py::test_real_command_execution -x` | ❌ Wave 0 |
| VER-03 | One CriterionVerification per AcceptanceProbe | unit | `pytest tests/test_autopilot_verify.py::test_per_criterion_evidence -x` | ❌ Wave 0 |
| VER-04 | Retry loop fires when overall_status=failed | integration | `pytest tests/test_autopilot_orchestrator.py::TestVerifyRetryLoop -x` | ❌ Wave 0 |
| VER-05 | Probe generated when test_commands empty | unit | `pytest tests/test_autopilot_verify.py::test_probe_generation -x` | ❌ Wave 0 |
| VER-06 | Playwright path skipped when unavailable | unit | `pytest tests/test_autopilot_verify.py::test_playwright_skipped -x` | ❌ Wave 0 |
| WORK-01 | plan/build/ship workflow.md has attribution header | unit | `pytest tests/test_autopilot_loader.py::test_vendored_workflow_attribution -x` | ❌ Wave 0 |
| WORK-02 | spec_prep workflow.md is non-trivial (>500 chars) | unit | `pytest tests/test_autopilot_loader.py::test_default_registry_workflow_content_is_real -x` | ❌ Wave 0 |
| WORK-03 | verify workflow.md is non-trivial (>500 chars) | unit | `pytest tests/test_autopilot_loader.py::test_default_registry_workflow_content_is_real -x` | ❌ Wave 0 |
| WORK-04 | End-to-end with real workflows replaces stubs | integration | `pytest tests/test_autopilot_orchestrator.py::TestEndToEnd -x` | ✅ (extend existing) |
| PERS-03 | ShipArtifact has branch_name, head_sha, release_notes, rollback_plan | unit | `pytest tests/test_autopilot_verify.py::test_ship_artifact_fields -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_autopilot_orchestrator.py tests/test_autopilot_loader.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/ -x -q`
- **Phase gate:** Full suite green (834 tests + new phase tests) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_autopilot_prep.py` — covers PREP-01..PREP-05
- [ ] `tests/test_autopilot_verify.py` — covers VER-01..VER-06, PERS-03
- [ ] `tests/test_autopilot_orchestrator.py::TestVerifyRetryLoop` — covers VER-04 orchestrator wiring (add to existing file)
- [ ] New assertion in `test_default_registry_has_workflow_content` or new test `test_default_registry_workflow_content_is_real` — covers WORK-01..WORK-03

## Agent-Skills Reference Content

**Commit pinned:** `bf2fa6994407c9c888fc19a03fd54957991cfa0e` (2026-04-15)

### planning-and-task-breakdown — Key Sections to Keep
- The Planning Process (Steps 1-5)
- Task Sizing (XS to XL scale)
- Red Flags section

**Drop:** When to Use, Common Rationalizations, Plan Document Template (replaced by PlanArtifact schema), skill invocation patterns.

### incremental-implementation — Key Sections to Keep
- The Increment Cycle (Implement → Test → Verify → Commit)
- Implementation Rules (Rule 0 through Rule 5)
- Increment Checklist
- Red Flags

**Drop:** When to Use, Working with Agents (human education), Common Rationalizations.

### shipping-and-launch — Key Sections to Keep
- Pre-Launch Checklist (six dimensions)
- Rollback Strategy
- Post-Launch Verification (first-hour checks)
- Red Flags

**Drop:** Feature Flag Strategy details (not MVP scope), Staged Rollout Sequence (Tier 3 approval concern, not Phase 31), Monitoring and Observability (post-MVP).

**Expected adaptation:** ~40-60% of original content as specified in AUTOPILOT-ROADMAP.md Section 8.

## Sources

### Primary (HIGH confidence)
- `/Users/kirankrishna/Documents/agentcouncil/agentcouncil/autopilot/orchestrator.py` — LinearOrchestrator, StageRunner type, stub factories
- `/Users/kirankrishna/Documents/agentcouncil/agentcouncil/autopilot/artifacts.py` — all artifact models with validators
- `/Users/kirankrishna/Documents/agentcouncil/agentcouncil/autopilot/loader.py` — StageManifest, SourceProvenance, ManifestLoader
- `/Users/kirankrishna/Documents/agentcouncil/docs/AUTOPILOT-ROADMAP.md` — Sections 3.9, 5.8, 8, 9 Phase 6 acceptance criteria
- `/Users/kirankrishna/Documents/agentcouncil/.planning/REQUIREMENTS.md` — PREP-*, VER-*, WORK-*, PERS-03 definitions
- `tests/test_autopilot_orchestrator.py` — existing e2e test to extend
- `tests/test_autopilot_loader.py` — existing loader tests with content assertions

### Secondary (MEDIUM confidence)
- `https://github.com/addyosmani/agent-skills` commit `bf2fa69` — agent-skills skill content for plan, build, ship workflows (fetched 2026-04-15)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already used in codebase
- Architecture: HIGH — StageRunner interface, SourceProvenance, artifact contracts all defined in existing code
- Pitfalls: HIGH — derived from reading actual orchestrator code and artifact validators
- Verify retry loop wiring: MEDIUM — requires new orchestrator behavior not yet implemented; see Open Questions

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (stable Python stdlib + Pydantic v2; agent-skills commit pinned)
