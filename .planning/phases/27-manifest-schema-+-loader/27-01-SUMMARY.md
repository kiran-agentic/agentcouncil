---
phase: 27-manifest-schema-+-loader
plan: 01
subsystem: autopilot
tags: [manifest, loader, yaml, pydantic, registry, phase-27]
dependency_graph:
  requires: [agentcouncil/autopilot/artifacts.py]
  provides: [agentcouncil/autopilot/loader.py, agentcouncil/autopilot/workflows/*/manifest.yaml]
  affects: [agentcouncil/autopilot/__init__.py, Phase-30-orchestrator]
tech_stack:
  added: [pyyaml>=6.0]
  patterns: [pydantic-first YAML schema, two-pass loader validation, frozen dataclass registry entry]
key_files:
  created:
    - agentcouncil/autopilot/loader.py
    - agentcouncil/autopilot/workflows/spec_prep/manifest.yaml
    - agentcouncil/autopilot/workflows/spec_prep/workflow.md
    - agentcouncil/autopilot/workflows/plan/manifest.yaml
    - agentcouncil/autopilot/workflows/plan/workflow.md
    - agentcouncil/autopilot/workflows/build/manifest.yaml
    - agentcouncil/autopilot/workflows/build/workflow.md
    - agentcouncil/autopilot/workflows/verify/manifest.yaml
    - agentcouncil/autopilot/workflows/verify/workflow.md
    - agentcouncil/autopilot/workflows/ship/manifest.yaml
    - agentcouncil/autopilot/workflows/ship/workflow.md
    - tests/test_autopilot_loader.py
  modified:
    - agentcouncil/autopilot/__init__.py
    - pyproject.toml
decisions:
  - "[Phase 27] KNOWN_ARTIFACT_TYPES is a frozenset constant in loader.py — avoids circular import with artifacts.py while maintaining single source of truth for valid artifact names"
  - "[Phase 27] build/ workflow dir force-added to git because top-level .gitignore has 'build/' pattern that wrongly matched agentcouncil/autopilot/workflows/build/"
  - "[Phase 27] StageRegistryEntry is a frozen dataclass (not Pydantic) — manifests are configuration data, not domain objects; frozen ensures registry immutability after load"
metrics:
  duration: "~4 minutes"
  completed_date: "2026-04-15"
  tasks_completed: 3
  files_created: 12
  files_modified: 2
  tests_added: 29
  test_count_total: 768
---

# Phase 27 Plan 01: Manifest Schema + Loader Summary

Startup-time manifest validation layer with Pydantic StageManifest model, two-pass ManifestLoader, five default stage manifests, and 29-test suite covering ORCH-01 and ORCH-02.

## What Was Built

### loader.py
- `KNOWN_ARTIFACT_TYPES: frozenset[str]` — 7 artifact type names (no class import, avoids circular dependency)
- `SourceProvenance(BaseModel)` — optional attribution block for vendored workflow content
- `StageManifest(BaseModel)` — Pydantic model with Literal fields for stage_type/default_gate/side_effect_level/retry_policy; `check_artifact_types` model_validator raises `ValueError("... not a known artifact type")` at construction time
- `StageRegistryEntry` — frozen dataclass with `manifest: StageManifest` and `workflow_content: str`
- `ManifestLoader` — two-pass loader: Pass 1 parses each manifest independently (Pydantic validates), Pass 2 validates all `allowed_next` references against the full registry; raises `FileNotFoundError` for missing root, `ValueError` for unknown stage references
- `load_default_registry()` — `__file__`-relative convenience function

### Five Workflow Manifests
Each stage follows the pipeline chain: spec_prep -> plan -> build -> verify -> ship (terminal)

| Stage | input_artifact | output_artifact | default_gate | side_effects |
|-------|---------------|----------------|--------------|--------------|
| spec_prep | null | SpecPrepArtifact | none | none |
| plan | SpecPrepArtifact | PlanArtifact | review_loop | none |
| build | PlanArtifact | BuildArtifact | review_loop | local |
| verify | BuildArtifact | VerifyArtifact | challenge | local |
| ship | VerifyArtifact | ShipArtifact | none | local |

### __init__.py
Updated to re-export both `artifacts` and `loader` public APIs using a combined `__all__`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Error message split across string literal lines**
- **Found during:** Task 1 acceptance criteria verification
- **Issue:** `grep -q "not a known artifact type"` failed because the message was split as `"is not a known artifact "` + `"type."` across two f-string lines — grep cannot see multi-line string concatenation
- **Fix:** Moved "not a known artifact type" to the first line of the f-string: `f"... is not a known artifact type. "`
- **Files modified:** agentcouncil/autopilot/loader.py
- **Commit:** 68bf9b4 (included in same commit)

**2. [Rule 2 - Missing] build/ workflow directory gitignored**
- **Found during:** Task 2 commit
- **Issue:** `.gitignore` has top-level `build/` pattern; git refused to stage `agentcouncil/autopilot/workflows/build/` without `-f`
- **Fix:** Used `git add -f` for the build workflow files and committed in a separate commit; documented in decision log
- **Files modified:** agentcouncil/autopilot/workflows/build/manifest.yaml, agentcouncil/autopilot/workflows/build/workflow.md
- **Commit:** 9353a9c

## Known Stubs

- All five `workflow.md` files are placeholders with text "Placeholder -- real workflow content will be added in Phase 31." This is intentional — the plan explicitly specifies placeholder content for Phase 27, with real workflow content deferred to Phase 31. The plan's goal (manifest schema + loader) is fully achieved; the stubs do not prevent any plan objective from being met.

## Self-Check: PASSED
