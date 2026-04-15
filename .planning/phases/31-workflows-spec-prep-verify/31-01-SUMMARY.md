---
phase: 31-workflows-spec-prep-verify
plan: 01
subsystem: autopilot-workflows
tags: [workflows, agent-skills, vendoring, attribution, spec-prep, verify]
dependency_graph:
  requires: []
  provides: [workflow-content-plan, workflow-content-build, workflow-content-ship, workflow-content-spec-prep, workflow-content-verify, third-party-notices]
  affects: [autopilot-loader, autopilot-registry, all-stage-runners]
tech_stack:
  added: []
  patterns: [MIT-attribution-header, source-provenance-yaml-block, agentcouncil-native-workflow]
key_files:
  created:
    - THIRD_PARTY_NOTICES.md
  modified:
    - agentcouncil/autopilot/workflows/plan/workflow.md
    - agentcouncil/autopilot/workflows/build/workflow.md
    - agentcouncil/autopilot/workflows/ship/workflow.md
    - agentcouncil/autopilot/workflows/spec_prep/workflow.md
    - agentcouncil/autopilot/workflows/verify/workflow.md
    - agentcouncil/autopilot/workflows/plan/manifest.yaml
    - agentcouncil/autopilot/workflows/build/manifest.yaml
    - agentcouncil/autopilot/workflows/ship/manifest.yaml
decisions:
  - "plan/build/ship workflow.md files are editorial adaptations of agent-skills SKILL.md at ~50% survival rate, dropping slash command refs, hook system refs, and templates replaced by typed artifacts"
  - "spec_prep/workflow.md and verify/workflow.md are fully AgentCouncil-native — no agent-skills content, no attribution header"
  - "source_provenance YAML block added to plan/build/ship manifests only; spec_prep and verify manifests left untouched"
metrics:
  duration_seconds: 212
  completed_date: "2026-04-15"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 8
---

# Phase 31 Plan 01: Vendor Workflows + Source Provenance Summary

Replaced five placeholder workflow.md files (5 words each) with real execution recipes: three MIT-attributed adaptations of agent-skills (plan, build, ship) and two AgentCouncil-native workflows (spec_prep, verify). Added `source_provenance` blocks to the three vendored manifests and created THIRD_PARTY_NOTICES.md at repo root.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Fetch agent-skills reference and write all five workflow.md files | 1e3a552 | plan/workflow.md, build/workflow.md, ship/workflow.md, spec_prep/workflow.md, verify/workflow.md |
| 2 | Update vendored manifests with source_provenance + create THIRD_PARTY_NOTICES.md | c9bc222 | plan/manifest.yaml, build/manifest.yaml, ship/manifest.yaml, THIRD_PARTY_NOTICES.md |

## What Was Built

### Vendored Workflows (plan, build, ship)

Each file starts with an HTML comment attribution header referencing the agent-skills repo, commit `bf2fa6994407c9c888fc19a03fd54957991cfa0e`, and MIT license. Content was adapted at approximately 50% survival rate:

- **plan/workflow.md**: Kept The Planning Process (Steps 1-5), Task Sizing table (XS-XL), Red Flags. Added PlanArtifact and AcceptanceProbe schema reference sections. Dropped Plan Document Template (replaced by typed artifact), slash command refs, hook system refs.
- **build/workflow.md**: Kept The Increment Cycle, Implementation Rules (Rule 0-5), Increment Checklist, Red Flags. Added BuildArtifact schema reference. Dropped "Working with Agents" (human education), Common Rationalizations.
- **ship/workflow.md**: Kept Pre-Launch Checklist (six dimensions), Rollback Strategy, Post-Launch Verification. Added ShipArtifact schema reference. Dropped Feature Flag Strategy details, Staged Rollout Sequence, Monitoring and Observability.

### Native Workflows (spec_prep, verify)

Written from scratch using AUTOPILOT-ROADMAP.md as the design spec:

- **spec_prep/workflow.md**: Three sub-steps (Codebase Research, Spec Refinement, Architecture Review), question priority ordering (10 priorities), spec readiness checklist (8 checks), SpecPrepArtifact schema reference. Implements Section 3.9.
- **verify/workflow.md**: Infrastructure discovery process, five verification levels (static/unit/integration/smoke/e2e) with per-level dispatch guidance, per-criterion evidence collection spec, retry guidance rules, VerifyArtifact schema reference. Implements Section 5.8.

### Source Provenance + Attribution

- Three manifest.yaml files updated with `source_provenance` blocks using exact SourceProvenance model field names (repo, path, license, commit, date_copied, modified).
- THIRD_PARTY_NOTICES.md created at repo root listing all three derived files with MIT copyright attribution.
- spec_prep and verify manifests left untouched (no source_provenance — native content).

## Verification Results

All verification passed:

```
python3 -c "from agentcouncil.autopilot.loader import load_default_registry ..." → All manifest + notices validated
python3 -m pytest tests/test_autopilot_loader.py -x -q → 29 passed in 0.08s
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] build/ directory ignored by .gitignore**
- **Found during:** Task 1 commit
- **Issue:** `.gitignore` contains `build/` which matched `agentcouncil/autopilot/workflows/build/`. `git add` refused to stage the file.
- **Fix:** Used `git add -f` to force-add the specific files inside the ignored directory. Applied to both workflow.md and manifest.yaml in the build/ workflow subdirectory.
- **Files modified:** N/A (git operation, no code change)
- **Commit:** Addressed inline in both task commits

## Known Stubs

None — all five workflow.md files contain substantive content (>500 chars each). The plan stage references PlanArtifact/AcceptanceProbe schemas by field name, not by placeholder values.

## Self-Check: PASSED
