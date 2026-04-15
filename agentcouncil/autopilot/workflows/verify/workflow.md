# Verify Stage Workflow

The verify stage proves the build works through executable evidence. It does not repeat the build — it executes the acceptance probes from `PlanArtifact.acceptance_probes` against the completed build and collects structured evidence per criterion.

The verify stage produces a `VerifyArtifact` with per-criterion verdicts. If verification fails, it sets `retry_recommendation="retry_build"` and `revision_guidance` so the orchestrator can re-run the build stage with targeted fix instructions.

## Infrastructure Discovery

Before executing any verification, discover and validate the environment:

```
VerificationEnvironment:
  project_types        — detected project types: python, node, frontend, api, cli
  test_commands        — runnable test commands (from pyproject.toml, package.json, Makefile)
  dev_server_command   — how to start the dev server (if needed)
  service_commands     — docker-compose up or equivalent
  health_checks        — endpoints or commands to confirm service readiness
  required_env_vars    — env vars that must be set
  missing_env_vars     — required env vars that are NOT set (these are blockers)
  playwright_available — True if playwright Python package or @playwright/test found
  confidence           — high | medium | low
```

Discovery uses file system inspection only — no commands are run during discovery. If `missing_env_vars` is non-empty, the affected criteria become `blocked` with `blocker_type="missing_env_var"`.

**Probe generation:** If `test_commands` is empty and acceptance probes require unit or integration verification, generate a minimal pytest probe file from the `AcceptanceProbe` entries. Use `probe_id` as the test function name prefix. Generated probes are listed in `VerifyArtifact.generated_tests`.

## Five Verification Levels

Dispatch per `AcceptanceProbe.verification_level`:

### verification_level = "static"

Static checks require no execution. Use for:
- File existence checks
- Import validation (`python3 -c "import module"`)
- Syntax validation
- Schema conformance checks

Evidence: `CommandEvidence` with the static check command, exit code, stdout showing the result.

### verification_level = "unit"

Isolated function/class tests with no external services. Use for:
- Logic correctness
- Error handling paths
- Input validation

Commands: Run the project's unit test suite filtered to the relevant module or function. Capture full exit code and stdout/stderr tail. Evidence: one `CommandEvidence` per command run.

### verification_level = "integration"

Tests that cross module or process boundaries but do not require a browser. Mocks are **forbidden** (`mock_policy="forbidden"`) at this level — real service interactions are required.

Service lifecycle for integration level:
1. Start required services (from `probe.service_requirements`)
2. Wait for health checks to pass (retry up to 30s)
3. Run integration test command
4. Capture `CommandEvidence` and `ServiceEvidence`
5. Teardown services after probe completes (even on failure)

If a service fails to start, set criterion `status="blocked"` with `blocker_type="service_unavailable"`.

### verification_level = "smoke"

End-to-end happy path through the real system. Tests the most critical user-facing behavior with real infrastructure.

Same service lifecycle as integration. Smoke tests should complete within 60 seconds per probe. If they time out, set `status="failed"` with `failure_diagnosis="timeout"`.

### verification_level = "e2e"

Browser-driven end-to-end tests. Only runs when `VerificationEnvironment.playwright_available=True`.

When Playwright is available:
1. Start dev server (`test_environment.dev_server_command`)
2. Wait for server health check
3. Run Playwright test script (or generate minimal test from probe description)
4. Capture screenshots and traces as `artifacts`
5. Tear down dev server

When Playwright is unavailable: set `status="skipped"` with `skip_reason="playwright_not_available"`. This is acceptable — record it honestly.

## Per-Criterion Evidence Collection

For each probe in `PlanArtifact.acceptance_probes`, produce one `CriterionVerification`:

```
CriterionVerification:
  criterion_id      — "ac-{index}" matching AcceptanceProbe.criterion_id
  criterion_text    — the acceptance criterion text
  status            — passed | failed | blocked | skipped
  verification_level — static | unit | integration | smoke | e2e
  mock_policy       — from probe (allowed | forbidden | not_applicable)
  evidence_summary  — human-readable explanation of what was checked and what was found
  commands          — list[CommandEvidence] (exact commands run with exit codes)
  services          — list[ServiceEvidence] (services started for this check)
  artifacts         — screenshots, traces, log paths
  failure_diagnosis — what went wrong (required when status=failed)
  revision_guidance — actionable fix direction (required when status=failed)
  skip_reason       — why skipped (required when status=skipped)
  blocker_type      — what blocked execution (required when status=blocked)
```

Rules:
- `status="passed"` requires exit_code=0 on all commands and all service health checks passing
- `status="failed"` requires non-empty `failure_diagnosis` and `revision_guidance`
- `status="blocked"` requires non-empty `blocker_type`
- `status="skipped"` requires non-empty `skip_reason`
- Behavior-changing criteria with `mock_policy="forbidden"` must have real execution evidence

## Retry Guidance

After all probes are evaluated, compute `overall_status`:
- `"passed"` — all criteria verdicts are "passed" (no failed, blocked, or unjustified skipped)
- `"failed"` — at least one criterion is "failed"
- `"blocked"` — at least one criterion is "blocked" and none are "failed"

When `overall_status != "passed"`:
- Set `retry_recommendation="retry_build"` if failures are fixable by re-implementing code
- Set `retry_recommendation="retry_plan"` if the plan itself was wrong (wrong approach, wrong target files)
- Set `retry_recommendation="block"` if failures cannot be resolved without user input (missing credentials, impossible requirement)
- Set `retry_recommendation="none"` only when overall_status="passed"

`revision_guidance` must be non-empty when `retry_recommendation="retry_build"`. It is the actionable instructions for the build stage in the next iteration: which files to fix, what the failure indicated, which test commands to run to confirm the fix.

## VerifyArtifact Schema Reference

```
VerifyArtifact:
  verify_id           — unique identifier (e.g., "verify-abc1234")
  build_id            — from BuildArtifact.build_id
  plan_id             — from PlanArtifact.plan_id
  spec_id             — from SpecArtifact.spec_id

  # Environment
  test_environment    — VerificationEnvironment discovered during this run

  # Evidence
  criteria_verdicts   — list[CriterionVerification] (one per AcceptanceProbe)
  overall_status      — passed | failed | blocked
  services_started    — all services started during verification (for teardown audit)
  generated_tests     — probe files created by verify when no test infrastructure existed
  coverage_gaps       — criteria or areas without verification evidence

  # Retry guidance
  retry_recommendation — none | retry_build | retry_plan | block
  revision_guidance   — actionable fix instructions (required when retry_recommendation="retry_build")
  failure_summary     — human-readable summary of what failed and why
```
