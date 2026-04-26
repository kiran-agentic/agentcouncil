<!--
Originally from: https://github.com/addyosmani/agent-skills
Path: skills/shipping-and-launch/SKILL.md
License: MIT (Addy Osmani, 2025)
Copied: 2026-04-15, commit bf2fa6994407c9c888fc19a03fd54957991cfa0e
Modified for AgentCouncil autopilot integration
-->

# Ship Stage Workflow

The ship stage is deterministic readiness packaging. By this point everything is already verified (and optionally challenged). Ship does not gate quality — it assembles the evidence into a `ShipArtifact` that describes what was built, how to verify it is working, and how to roll it back if needed.

Ship has no council gate. If the work needed to stop, it should have stopped at verify or challenge.

Every launch should be reversible, observable, and incremental.

## Pre-Launch Checklist

Work through each dimension before declaring recommended_action="ship":

**1. Functional Correctness**
- `VerifyArtifact.overall_status == "passed"`
- All acceptance criteria have a verdict of "passed" in `criteria_verdicts`
- No criteria_verdicts with status "failed" or "blocked"
- Coverage gaps documented in `VerifyArtifact.coverage_gaps` are explicitly noted in `ShipArtifact.remaining_risks`

**2. Code Quality**
- `BuildArtifact.all_tests_passing == True`
- No known broken tests in the commit range
- No uncommitted changes in the working tree (`worktree_clean == True`)
- No TODO comments that should be resolved before launch
- No debug statements in production code
- Error handling covers expected failure modes

**3. Security**
- No secrets in code or version control
- Input validation on all user-facing endpoints
- Authentication and authorization checks in place
- CORS configured to specific origins (not wildcard)

**4. Safety and Reversibility**
- A rollback plan exists and is executable (`rollback_plan` is non-empty)
- The rollback plan identifies the specific commit SHA to revert to
- If migration was part of the build, rollback plan includes rollback migration step
- The rollback plan must be executable by someone who was not involved in the build

**5. Delivery Conventions**
- `branch_name` is the current working branch
- `head_sha` is the HEAD commit at time of ship packaging
- Release notes summarize user-visible changes (not implementation details)
- Relevant convention files (CHANGELOG, version file) are noted in release notes if they exist

**6. Risk Identification**
- `remaining_risks` lists anything from `VerifyArtifact.coverage_gaps` that was not resolved
- Any Tier 3 escalation triggers from the run are documented
- Known unknowns are explicit, not silently dropped

**7. Recommended Action**
- `recommended_action="ship"` requires: `tests_passing=True`, `acceptance_criteria_met=True`, `worktree_clean=True`, `blockers=[]`, `rollback_plan` non-empty
- `recommended_action="hold"` is appropriate if any of the above conditions is not met
- Never set `recommended_action="ship"` to make the invariant check pass when the work is not ready

## Rollback Strategy

The rollback plan is the answer to: "If this causes a production incident in the first hour, what is the exact sequence of commands to undo it?"

For code changes:
```
git revert {head_sha}
git push origin {branch_name}
```

For schema migrations: include the rollback migration command explicitly — do not assume the reviewer knows it.

For dependency upgrades: include the specific version to revert to.

**Time to rollback targets:**
- Feature flag: < 1 minute
- Redeploy previous version: < 5 minutes
- Database rollback: < 15 minutes

## Staged Rollout (when applicable)

For user-facing features, ship behind feature flags to decouple deployment from release:

```
1. DEPLOY with flag OFF     → Code is in production but inactive
2. ENABLE for team/beta     → Internal testing in production environment
3. GRADUAL ROLLOUT          → 5% → 25% → 50% → 100% of users
4. MONITOR at each stage    → Watch error rates, performance, user feedback
5. CLEAN UP                 → Remove flag and dead code path after full rollout
```

### Rollout Decision Thresholds

| Metric | Advance (green) | Hold (yellow) | Roll back (red) |
|--------|-----------------|---------------|-----------------|
| Error rate | Within 10% of baseline | 10-100% above baseline | >2x baseline |
| P95 latency | Within 20% of baseline | 20-50% above baseline | >50% above baseline |
| Client JS errors | No new error types | New errors at <0.1% of sessions | New errors at >0.1% of sessions |
| Business metrics | Neutral or positive | Decline <5% (may be noise) | Decline >5% |

## Post-Launch Verification

After the artifact is handed off, the following first-hour checks confirm the ship was successful:

1. The verification commands from `VerifyArtifact.test_environment.test_commands` still pass on the shipped branch
2. Any services declared in `VerifyArtifact.services_started` are responding
3. Health endpoints (from `test_environment.health_checks`) return healthy status
4. No error rate spike in the first 10 minutes of operation
5. Critical user flow works end-to-end
6. Logs are flowing and readable
7. Rollback mechanism verified ready

## Monitoring and Observability

```
Application metrics:
├── Error rate (total and by endpoint)
├── Response time (p50, p95, p99)
├── Request volume
├── Active users
└── Key business metrics (conversion, engagement)

Infrastructure metrics:
├── CPU and memory utilization
├── Database connection pool usage
├── Disk space
├── Network latency
└── Queue depth (if applicable)

Client metrics:
├── Core Web Vitals (LCP, INP, CLS)
├── JavaScript errors
├── API error rates from client perspective
└── Page load time
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It works in staging, it'll work in production" | Production has different data, traffic patterns, and edge cases. Monitor after deploy. |
| "We don't need feature flags for this" | Every feature benefits from a kill switch. Even "simple" changes can break things. |
| "Monitoring is overhead" | Not having monitoring means you discover problems from user complaints instead of dashboards. |
| "We'll add monitoring later" | Add it before launch. You can't debug what you can't see. |
| "Rolling back is admitting failure" | Rolling back is responsible engineering. Shipping a broken feature is the failure. |
| "It's Friday afternoon, let's ship it" | No. |

## Red Flags in Ship

Do not produce `recommended_action="ship"` if:
- `VerifyArtifact.overall_status != "passed"`
- There are uncommitted changes in the working tree
- The rollback plan references a SHA that does not exist
- Coverage gaps include any criterion with `mock_policy="forbidden"` that was never resolved
- Any Tier 3 promotion that required human approval has not been resolved
- `BuildArtifact.all_tests_passing == False`
- No monitoring or error reporting in production
- Production environment configuration done by memory, not code

If any red flag fires, set `recommended_action="hold"` and document the blockers explicitly.

## ShipArtifact Schema Reference

The ship stage must produce a valid `ShipArtifact`:

```
ShipArtifact:
  ship_id           — unique identifier (e.g., "ship-abc1234")
  verify_id         — from VerifyArtifact.verify_id (traceability)
  build_id          — from BuildArtifact.build_id (traceability)
  plan_id           — from PlanArtifact.plan_id (traceability)
  spec_id           — from SpecArtifact.spec_id (traceability)

  # Delivery state
  branch_name       — current git branch
  head_sha          — HEAD commit SHA at time of packaging
  worktree_clean    — True if no uncommitted changes

  # Quality gates
  tests_passing     — True if all tests passed in verify
  acceptance_criteria_met — True if verify overall_status == "passed"
  blockers          — list of blocking issues (must be empty for recommended_action="ship")

  # Packaging
  readiness_summary — narrative summary of what was built and why it is ready
  release_notes     — user-visible change summary
  rollback_plan     — exact commands to undo this change

  # Outcome
  recommended_action — "ship" | "hold"
  remaining_risks   — known gaps from VerifyArtifact.coverage_gaps
```
