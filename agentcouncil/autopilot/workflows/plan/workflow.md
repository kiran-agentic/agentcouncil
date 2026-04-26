<!--
Originally from: https://github.com/addyosmani/agent-skills
Path: skills/planning-and-task-breakdown/SKILL.md
License: MIT (Addy Osmani, 2025)
Copied: 2026-04-15, commit bf2fa6994407c9c888fc19a03fd54957991cfa0e
Modified for AgentCouncil autopilot integration
-->

# Plan Stage Workflow

The planning stage decomposes an enriched spec into an ordered task breakdown, producing a `PlanArtifact` ready for the build stage. The plan must design not only what to build but how each acceptance criterion will be verified.

Good task breakdown is the difference between an agent that completes work reliably and one that produces a tangled mess. Every task should be small enough to implement, test, and verify in a single focused session.

## The Planning Process

**Step 1: Read and parse the spec completely**

Before writing a single task, read the full `SpecPrepArtifact`:
- All requirements (binding)
- All acceptance criteria (each must map to at least one `AcceptanceProbe`)
- Non-goals (tasks that would implement these are bugs in the plan)
- Research findings (target files, existing patterns, sensitive areas)
- Architecture notes and binding decisions

Do not begin decomposing until the full spec is internalized.

**Do NOT write code during planning.** The output is a plan document, not implementation.

**Step 2: Identify the dependency graph**

Map what depends on what:

```
Database schema
    │
    ├── API models/types
    │       │
    │       ├── API endpoints
    │       │       │
    │       │       └── Frontend API client
    │       │               │
    │       │               └── UI components
    │       │
    │       └── Validation logic
    │
    └── Seed data / migrations
```

Look for natural seams in the work:
- Data model changes first (schema before logic that uses it)
- Interface definition before implementation
- Shared utilities before callers
- Infrastructure setup before feature code
- Test scaffolding before behavior

Implementation order follows the dependency graph bottom-up: build foundations first. Each task should represent a logical unit that could be reviewed in isolation.

**Step 3: Slice vertically**

Instead of building all the database, then all the API, then all the UI — build one complete feature path at a time:

**Bad (horizontal slicing):**
```
Task 1: Build entire database schema
Task 2: Build all API endpoints
Task 3: Build all UI components
Task 4: Connect everything
```

**Good (vertical slicing):**
```
Task 1: User can create an account (schema + API + UI for registration)
Task 2: User can log in (auth schema + API + UI for login)
Task 3: User can create a task (task schema + API + UI for creation)
Task 4: User can view task list (query + API + UI for list view)
```

Each vertical slice delivers working, testable functionality.

**Step 4: Size and order tasks**

Use this scale:

| Size | Files | Description | Example |
|------|-------|-------------|---------|
| XS   | 1     | Single function or constant | Add a config field, fix a typo |
| S    | 1-2   | Single class or small module | Add a method to an existing service |
| M    | 3-5   | One logical unit with tests | New endpoint with handler + tests |
| L    | 5-8   | Multi-file change | New subsystem with 2-4 files |
| XL   | 8+    | **Split this task** | XL tasks are a planning failure |

If a task is L or larger, it should be broken into smaller tasks. An agent performs best on S and M tasks.

**When to break a task down further:**
- It would take more than one focused session (roughly 2+ hours of agent work)
- You cannot describe the acceptance criteria in 3 or fewer bullet points
- It touches two or more independent subsystems (e.g., auth and billing)
- You find yourself writing "and" in the task title (a sign it is two tasks)

Ordering constraints:
- Data/schema before logic
- Interfaces before implementations
- Shared code before consumers
- Tests can be written alongside or after the code they test
- Never create a circular dependency between tasks
- High-risk tasks are early (fail fast)

**Step 5: Write acceptance probes for each spec criterion**

Every item in `SpecPrepArtifact.finalized_spec.acceptance_criteria` must have at least one `AcceptanceProbe` in `PlanArtifact.acceptance_probes`.

For each probe:
- Choose the verification level: `static`, `unit`, `integration`, `smoke`, `e2e`
- Behavior-changing criteria must have at least one probe with `mock_policy="forbidden"` and level `integration`, `smoke`, or `e2e`
- Specify exact `expected_observation` (what does passing look like)
- List `service_requirements` (postgres, redis, dev-server) — be conservative, list only what is actually needed
- Set `related_task_ids` to the tasks that implement this criterion
- If test infrastructure does not exist, note `command_hint` as "generate probe" — the verify stage will create it

**Step 6: Write the execution order and verification strategy**

`execution_order` is an ordered list of all `task_id` values. It is the sequence the build runner will follow.

Arrange tasks so that:
1. Dependencies are satisfied (build foundation first)
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)

`verification_strategy` is a short narrative describing the overall approach:
- Which test commands cover which criteria
- What services need to be running
- How end-to-end verification will work
- Any known gaps or conditional paths

## Parallelization Opportunities

When multiple agents or sessions are available:

- **Safe to parallelize:** Independent feature slices, tests for already-implemented features, documentation
- **Must be sequential:** Database migrations, shared state changes, dependency chains
- **Needs coordination:** Features that share an API contract (define the contract first, then parallelize)

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll figure it out as I go" | That's how you end up with a tangled mess and rework. 10 minutes of planning saves hours. |
| "The tasks are obvious" | Write them down anyway. Explicit tasks surface hidden dependencies and forgotten edge cases. |
| "Planning is overhead" | Planning is the task. Implementation without a plan is just typing. |
| "I can hold it all in my head" | Context windows are finite. Written plans survive session boundaries and compaction. |

## Red Flags in Planning

Stop and reconsider the plan if:
- Any single task touches more than 5 files in unrelated areas
- A task has no clear, testable done condition
- The execution order has a cycle
- There are acceptance criteria with no corresponding probe
- The plan produces an artifact that is not the `SpecPrepArtifact.finalized_spec` output
- A task description starts with "try to" or "maybe" — this means unclear scope
- Any acceptance probe uses `mock_policy="allowed"` for behavior-changing criteria
- All tasks are XL-sized
- No checkpoints between tasks

## Verification

Before starting implementation, confirm:

- [ ] Every task has acceptance criteria
- [ ] Every task has a verification step
- [ ] Task dependencies are identified and ordered correctly
- [ ] No task touches more than ~5 files
- [ ] Checkpoints exist between major phases
- [ ] Every acceptance criterion has at least one AcceptanceProbe

## PlanArtifact Schema Reference

The plan stage must produce a valid `PlanArtifact`:

```
PlanArtifact:
  plan_id        — unique identifier (e.g., "plan-abc1234")
  spec_id        — from SpecPrepArtifact.finalized_spec.spec_id
  prep_id        — from SpecPrepArtifact.prep_id (traceability)
  tasks          — list[PlanTask] (non-empty)
  execution_order — list of task_ids in run sequence (must match tasks exactly)
  verification_strategy — narrative string
  acceptance_probes — list[AcceptanceProbe] (one per acceptance criterion minimum)

PlanTask:
  task_id        — unique within plan (e.g., "task-01")
  title          — short imperative description
  description    — what to build and why
  acceptance_criteria — testable conditions for this task
  depends_on     — list of task_ids this must wait for
  target_files   — files this task will create or modify
  estimated_complexity — small | medium | large

AcceptanceProbe:
  probe_id       — unique within plan
  criterion_id   — "ac-{index}" zero-indexed into spec.acceptance_criteria
  criterion_text — the criterion being verified
  verification_level — static | unit | integration | smoke | e2e
  target_behavior — what the probe checks
  command_hint   — suggested command (optional)
  service_requirements — services needed
  expected_observation — what success looks like
  mock_policy    — allowed | forbidden | not_applicable
  related_task_ids — task_ids that implement this criterion
  confidence     — high | medium | low
```
