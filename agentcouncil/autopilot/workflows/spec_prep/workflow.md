# Spec Prep Stage Workflow

The spec prep stage is the user's last high-bandwidth touchpoint. It transforms a rough user description or partial `SpecArtifact` into an autonomy-ready `SpecPrepArtifact`. After spec prep completes successfully, the user disengages and the autopilot proceeds without human input.

**Design principle:** Maximize autonomous executability per minute of user attention.

## Sub-Step 1: Codebase Research (Autonomous)

Before asking the user anything, inspect the repository. This prevents generic questions and uncovers real constraints.

**Research targets:**

| Target | What to find | Output field |
|--------|-------------|--------------|
| Target files | Which files will likely be modified | `likely_target_files` |
| Existing patterns | Frameworks, naming conventions, API patterns already in use | `existing_patterns` |
| Test infrastructure | Test framework, test commands, CI config, existing test files | `test_commands` |
| Sensitive paths | auth/, migrations/, infra/, permissions/, deploy/ directories | `sensitive_areas` |
| Service dependencies | docker-compose.yml, dev server commands, required env vars | (feeds VerificationEnvironment) |
| Delivery conventions | Branch naming from git history, PR templates, CHANGELOG, version files | (feeds ClarificationPlan assumptions) |
| Playwright availability | `package.json @playwright/test` or `playwright` Python package | (feeds VerificationEnvironment.playwright_available) |
| Unknown context | Things that cannot be determined without user input | `unknowns` |

Research uses file system inspection (pathlib), git history reading, and config file parsing. It does not run any build commands or start any services.

**Confidence rating:**
- `high` — target files clearly identified, test infrastructure confirmed, delivery conventions known
- `medium` — some gaps, but safe assumptions cover them
- `low` — significant unknowns; architecture review may be warranted

Output: `CodebaseResearchBrief` with populated `summary`, `relevant_files`, `existing_patterns`, `likely_target_files`, `test_commands`, `sensitive_areas`, `unknowns`, `confidence`.

## Sub-Step 2: Spec Refinement (Interactive)

Ask only blocking questions — those where a wrong assumption would cause rework, wrong user-visible behavior, safety risk, or tier promotion. Everything else becomes a documented assumption.

**Question budget:**
- Default: 0–3 blocking questions
- Hard maximum: 5
- Present assumptions alongside questions so the user can correct silently

**Question priority (ordered by impact on autonomous execution):**

1. **Acceptance criteria gaps** — what does "done" look like? (stop condition for verify)
2. **Scope boundaries** — what is explicitly out of scope?
3. **Conflict resolution** — existing code contradicts the request
4. **Risk/approval boundaries** — migrations, auth, deploys: are they allowed?
5. **Compatibility constraints** — must existing behavior remain unchanged?
6. **Verification environment** — only when research could not determine test/service infrastructure
7. **Delivery expectations** — only when research could not determine branch/PR/release conventions
8. **Decision preferences** — when two approaches are valid, which tradeoff does the user prefer?
9. **Priority guidance** — correctness vs. speed, simplicity vs. configurability
10. **Edge cases** — what should happen in specific boundary scenarios?

Categories 6 and 7 are only asked when codebase research failed to determine the answer. If `docker-compose.yml` was found, do not ask "do you use Docker?"

**Autonomous mode:** When running without an interactive user (programmatic invocation), skip all questions and document every uncertainty as an assumption. Set `ClarificationPlan.blocking_questions = []` and populate `assumptions` with what was inferred.

Output: `ClarificationPlan` with `blocking_questions`, `user_answers`, `assumptions`, `deferred_questions`.

## Sub-Step 3: Architecture Review (Conditional Council Brainstorm)

Run a council `brainstorm` only when triggered. Not every spec needs architecture review.

**Triggers (any one is sufficient):**
- Multiple viable implementation architectures exist
- Cross-module changes (touches 3+ distinct modules)
- Public schema or API surface changes
- Security, auth, migrations, permissions, deployment, or dependency changes
- Low confidence in inferred target files (`CodebaseResearchBrief.confidence == "low"`)
- Spec is minimal but blast radius appears large
- User explicitly requests architecture input

**When triggered:** Invoke the council `brainstorm` protocol with the spec and research brief as input. The output feeds `SpecPrepArtifact.architecture_notes`. This review narrows the implementation space — it does not replace the spec.

**When not triggered:** Skip entirely. Do not run a brainstorm to be thorough. The cost of unnecessary deliberation is always higher than the cost of a well-understood implementation choice.

## Spec Readiness Check

Before producing the `SpecPrepArtifact` and allowing autonomous execution to begin, validate all of the following. If any check fails, pause while the user is still present.

**Required:**
- [ ] At least one requirement in `SpecArtifact.requirements`
- [ ] At least one testable acceptance criterion in `SpecArtifact.acceptance_criteria`
- [ ] Clear non-goals, or explicit "none known"
- [ ] At least one inferred or declared target file with medium or higher confidence
- [ ] Known sensitive areas flagged (empty list is acceptable if research found none)
- [ ] Unresolved questions classified as blocking (asked) or assumptions (documented)
- [ ] **Verification feasibility:** test infrastructure identified, or a plan to generate probes exists; no unresolved credential or service blockers
- [ ] **Delivery clarity:** branch strategy, PR expectations, and release conventions are known or assumed

If readiness fails, do not enter `plan`. Return to sub-step 2 for the failed dimensions.

## SpecPrepArtifact Schema Reference

The spec prep stage must produce a valid `SpecPrepArtifact`:

```
SpecPrepArtifact:
  prep_id               — unique identifier (e.g., "prep-abc1234")
  finalized_spec        — SpecArtifact with requirements, acceptance_criteria, non_goals, target_files

  # Research and clarification
  research              — CodebaseResearchBrief from sub-step 1
  clarification         — ClarificationPlan from sub-step 2

  # Advisory context (guidance, not requirements)
  architecture_notes    — from optional arch review (empty list if not triggered)
  conventions_to_follow — "use pytest", "follow middleware pattern", etc.
  decision_preferences  — "prefer simplicity", "match existing patterns"
  priority_guidance     — "correctness over speed"

  # Binding vs advisory distinction
  binding_decisions     — user-confirmed decisions that must be followed
  advisory_context      — guidance that can be overridden with reason

  # Autonomy metadata
  recommended_tier      — 1 | 2 | 3 (default 2)
  escalation_triggers   — conditions that should promote the tier during execution
```
