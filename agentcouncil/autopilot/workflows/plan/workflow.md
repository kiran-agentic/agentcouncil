<!--
Originally from: https://github.com/addyosmani/agent-skills
Path: skills/planning-and-task-breakdown/SKILL.md
License: MIT (Addy Osmani, 2025)
Copied: 2026-04-15, commit bf2fa6994407c9c888fc19a03fd54957991cfa0e
Modified for AgentCouncil autopilot integration
-->

# Plan Stage Workflow

The planning stage decomposes an enriched spec into an ordered task breakdown, producing a `PlanArtifact` ready for the build stage. The plan must design not only what to build but how each acceptance criterion will be verified.

## The Planning Process

**Step 1: Read and parse the spec completely**

Before writing a single task, read the full `SpecPrepArtifact`:
- All requirements (binding)
- All acceptance criteria (each must map to at least one `AcceptanceProbe`)
- Non-goals (tasks that would implement these are bugs in the plan)
- Research findings (target files, existing patterns, sensitive areas)
- Architecture notes and binding decisions

Do not begin decomposing until the full spec is internalized.

**Step 2: Identify natural decomposition boundaries**

Look for natural seams in the work:
- Data model changes first (schema before logic that uses it)
- Interface definition before implementation
- Shared utilities before callers
- Infrastructure setup before feature code
- Test scaffolding before behavior

Each task should represent a logical unit that could be reviewed in isolation.

**Step 3: Size and order tasks**

Use this scale:

| Size | Description | Example |
|------|-------------|---------|
| XS   | Single function or constant | Add a config field, fix a typo in error message |
| S    | Single class or small module | Add a method to an existing service |
| M    | One logical unit with tests | New endpoint with handler + tests |
| L    | Multi-file change | New subsystem with 2-4 files |
| XL   | Split this task | XL tasks are a planning failure |

If a task is XL, split it. The plan is wrong, not the work.

Ordering constraints:
- Data/schema before logic
- Interfaces before implementations
- Shared code before consumers
- Tests can be written alongside or after the code they test
- Never create a circular dependency between tasks

**Step 4: Write acceptance probes for each spec criterion**

Every item in `SpecPrepArtifact.finalized_spec.acceptance_criteria` must have at least one `AcceptanceProbe` in `PlanArtifact.acceptance_probes`.

For each probe:
- Choose the verification level: `static`, `unit`, `integration`, `smoke`, `e2e`
- Behavior-changing criteria must have at least one probe with `mock_policy="forbidden"` and level `integration`, `smoke`, or `e2e`
- Specify exact `expected_observation` (what does passing look like)
- List `service_requirements` (postgres, redis, dev-server) — be conservative, list only what is actually needed
- Set `related_task_ids` to the tasks that implement this criterion
- If test infrastructure does not exist, note `command_hint` as "generate probe" — the verify stage will create it

**Step 5: Write the execution order and verification strategy**

`execution_order` is an ordered list of all `task_id` values. It is the sequence the build runner will follow.

`verification_strategy` is a short narrative describing the overall approach:
- Which test commands cover which criteria
- What services need to be running
- How end-to-end verification will work
- Any known gaps or conditional paths

## Red Flags in Planning

Stop and reconsider the plan if:
- Any single task touches more than 5 files in unrelated areas
- A task has no clear, testable done condition
- The execution order has a cycle
- There are acceptance criteria with no corresponding probe
- The plan produces an artifact that is not the `SpecPrepArtifact.finalized_spec` output
- A task description starts with "try to" or "maybe" — this means unclear scope
- Any acceptance probe uses `mock_policy="allowed"` for behavior-changing criteria

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
