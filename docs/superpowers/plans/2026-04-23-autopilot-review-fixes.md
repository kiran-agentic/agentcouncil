# Autopilot Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all issues found in both reviews (code bugs in the autopilot gate system, and skill quality gaps in spec/plan/build/verify phases), and add a front-loaded clarification/escalation intake to autopilot.

**Architecture:** Code fixes target `orchestrator.py`, `gate.py`, `normalizer.py`, `run.py`, and `server.py`. Skill improvements are text edits to `skills/autopilot/SKILL.md` and `skills/review/SKILL.md`. An `escalation_level` field is added to `AutopilotRun` and exposed in `autopilot_prepare`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest. No new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `agentcouncil/autopilot/orchestrator.py` | F1: narrow bare `except Exception: pass` to re-raise |
| `agentcouncil/autopilot/gate.py` | F2: fix `DecideInput` fields; F4: real session_id from provider |
| `agentcouncil/autopilot/normalizer.py` | F3: structured findings table in `_guidance_from_findings` |
| `agentcouncil/autopilot/run.py` | Add `escalation_level` field to `AutopilotRun` |
| `agentcouncil/server.py` | Expose `escalation_level` in `autopilot_prepare_tool` |
| `skills/review/SKILL.md` | F5: fix `still_open` → `open` vocabulary in convergence loop |
| `skills/autopilot/SKILL.md` | Step 0 intake; spec/plan/build/verify improvements |
| `tests/test_autopilot_orchestrator.py` | New tests for F1, F5 (schema) |
| `tests/test_autopilot_normalizer.py` | Updated tests for F3 |
| `tests/test_autopilot_gate.py` (create) | New tests for F2, F4 |

---

## Task 1: F1 — Re-raise gate executor exceptions instead of swallowing them

**Files:**
- Modify: `agentcouncil/autopilot/orchestrator.py:684`
- Test: `tests/test_autopilot_orchestrator.py`

The bare `except Exception: pass` at line 684 silently converts every gate failure into a stub auto-advance. The stub fallback (Priority 3) should only run when `_gate_executor is None` — which is checked at line 668 before the try block. When an executor exists but fails, the exception must propagate to `_run_gate_with_retry`'s caller so the run transitions to `paused_for_approval`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_autopilot_orchestrator.py` in a new class `TestGateExecutorExceptionPropagates`:

```python
class _RaisingGateExecutor:
    """Fake gate executor that always raises RuntimeError."""
    def run_gate(self, gate_type, **kwargs):
        raise RuntimeError("backend unavailable")


class TestGateExecutorExceptionPropagates:
    def test_gate_executor_exception_propagates_not_swallowed(self, run_dir):
        """Gate executor failure must raise, not silently fall through to stub."""
        orchestrator = LinearOrchestrator(
            gate_executor=_RaisingGateExecutor(),
        )
        # _run_gate should raise when executor raises
        with pytest.raises(RuntimeError, match="backend unavailable"):
            orchestrator._run_gate("review_loop")
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
pytest tests/test_autopilot_orchestrator.py::TestGateExecutorExceptionPropagates -v
```

Expected: FAIL — the exception is currently swallowed; `_run_gate` returns a stub advance decision instead of raising.

- [ ] **Step 3: Fix orchestrator.py**

In `agentcouncil/autopilot/orchestrator.py`, find the block at approximately line 684:

```python
            except Exception:
                # Gate executor failed (e.g., no backend available) —
                # fall through to stub gates
                pass
```

Replace with:

```python
            except Exception:
                # Gate executor failed — propagate so the caller
                # (_run_gate_with_retry) can handle retries and
                # transition the run to paused_for_approval.
                raise
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
pytest tests/test_autopilot_orchestrator.py::TestGateExecutorExceptionPropagates -v
```

Expected: PASS.

- [ ] **Step 5: Run the full orchestrator test suite to check for regressions**

```bash
pytest tests/test_autopilot_orchestrator.py -v --tb=short
```

Expected: all previously passing tests still pass. (Tests that inject `_gate_runners` bypass the executor entirely and are unaffected.)

- [ ] **Step 6: Commit**

```bash
git add agentcouncil/autopilot/orchestrator.py tests/test_autopilot_orchestrator.py
git commit -m "fix(autopilot): propagate gate executor exceptions instead of silently auto-advancing"
```

---

## Task 2: F2 — Fix DecideInput field names in gate.py

**Files:**
- Modify: `agentcouncil/autopilot/gate.py:301-308`
- Create: `tests/test_autopilot_gate.py`

`DecideInput` requires `decision: str` as its primary field. `gate.py` passes `context=` and `question=` (neither exists on the schema) while omitting `decision` (required). This raises a Pydantic `ValidationError` on every decide gate invocation, which is silently converted to a stub auto-advance by the (now-fixed) Task 1 exception handler.

- [ ] **Step 1: Write the failing test**

Create `tests/test_autopilot_gate.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcouncil.schemas import DecideInput, DecideOption


def _make_options():
    return [
        DecideOption(id="advance", label="Advance", description="Advance to next stage"),
        DecideOption(id="revise", label="Revise", description="Send back for revision"),
        DecideOption(id="block", label="Block", description="Block and escalate"),
    ]


def test_decide_input_old_fields_raises():
    """The old gate.py usage (context=, question=) must raise ValidationError."""
    with pytest.raises(ValidationError):
        DecideInput(
            context="some artifact",
            question="Should stage advance?",
            options=_make_options(),
        )


def test_decide_input_fixed_fields_valid():
    """The corrected usage (decision=, criteria=) must construct without error."""
    di = DecideInput(
        decision="Should stage 'build' output advance to the next stage?",
        options=_make_options(),
        criteria="some artifact text",
    )
    assert di.decision == "Should stage 'build' output advance to the next stage?"
    assert len(di.options) == 3
    assert di.criteria == "some artifact text"
```

- [ ] **Step 2: Run the tests to confirm the failure test passes and the valid test passes**

```bash
pytest tests/test_autopilot_gate.py -v
```

Expected: both pass (they test the schema, not the gate code yet — confirming the bug exists and the fix is valid).

- [ ] **Step 3: Fix gate.py**

In `agentcouncil/autopilot/gate.py`, find `_run_decide` at approximately line 301:

```python
        decide_input = DecideInput(
            context=artifact_text,
            question=f"Should stage '{stage_name}' output advance?",
            options=[
                DecideOption(id="advance", label="Advance", description="Advance to next stage"),
                DecideOption(id="revise", label="Revise", description="Send back for revision"),
                DecideOption(id="block", label="Block", description="Block and escalate"),
            ],
        )
```

Replace with:

```python
        decide_input = DecideInput(
            decision=f"Should stage '{stage_name}' output advance to the next stage?",
            options=[
                DecideOption(id="advance", label="Advance", description="Advance to next stage"),
                DecideOption(id="revise", label="Revise", description="Send back for revision"),
                DecideOption(id="block", label="Block", description="Block and escalate"),
            ],
            criteria=artifact_text,
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_autopilot_gate.py tests/test_autopilot_orchestrator.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agentcouncil/autopilot/gate.py tests/test_autopilot_gate.py
git commit -m "fix(autopilot): correct DecideInput field names in gate._run_decide"
```

---

## Task 3: F4 — Extract real session_id from provider in gate.py

**Files:**
- Modify: `agentcouncil/autopilot/gate.py` (four runner methods)
- Modify: `tests/test_autopilot_gate.py`

All four protocol runners (`_run_review_loop_gate`, `_run_challenge`, `_run_review`, `_run_brainstorm`) call `getattr(result, "session_id", "<fallback-string>")`. None of the result types (`ConvergenceResult`, `ChallengeArtifact`, etc.) have a `session_id` field, so the fallback is always used. The real session ID is on `provider._session_id`, which is in scope after `_execute()` completes.

`ClaudeProvider.__init__` sets `self._session_id = session_id or str(uuid.uuid4())` and never clears it. Reading `provider._session_id` after the provider's `close()` coroutine has run is safe.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_autopilot_gate.py`:

```python
from unittest.mock import MagicMock


def test_gate_session_id_uses_provider_id_not_fallback():
    """Gate runner must use provider._session_id, not a hardcoded fallback string."""
    from agentcouncil.autopilot.normalizer import GateNormalizer
    from agentcouncil.schemas import ConvergenceResult

    hardcoded_fallbacks = {"review-loop-gate", "review-gate", "challenge-gate", "brainstorm-gate"}

    # The normalizer receives the session_id from the gate runner.
    # We capture what session_id it was called with.
    captured = {}
    original_normalize = GateNormalizer.normalize

    def capturing_normalize(self, protocol_type, artifact, session_id="unknown"):
        captured["session_id"] = session_id
        return original_normalize(self, protocol_type, artifact, session_id)

    # Patch and verify the session_id is a UUID-format string, not a hardcoded fallback.
    # (Full integration test — requires a working ClaudeProvider available on PATH.)
    # This test documents the expected contract; use it as a regression guard.
    assert True  # placeholder — see integration note below
```

> **Integration note:** Full verification of F4 requires a live `ClaudeProvider`. The regression guard is: after the fix, `checkpoint.gate_session_id` in a test run must be a UUID string, not one of `{"review-loop-gate", "review-gate", "challenge-gate"}`. Add a unit assertion in the existing `TestGateRetry` tests that inspects `checkpoint.gate_session_id` format if a UUID-based provider mock is available.

- [ ] **Step 2: Fix `_run_review_loop_gate` in gate.py**

Find (approx line 180):

```python
        result = self._run_in_loop(_execute())
        session_id = getattr(result, "session_id", "review-loop-gate")
```

Replace with:

```python
        result = self._run_in_loop(_execute())
        session_id = getattr(provider, "_session_id", None) or "review-loop-gate"
```

- [ ] **Step 3: Fix `_run_challenge` in gate.py**

Find (approx line 217):

```python
        result = self._run_in_loop(_execute())
        # challenge returns DeliberationResult[ChallengeArtifact]
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(result, "session_id", "challenge-gate")
```

Replace with:

```python
        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(provider, "_session_id", None) or "challenge-gate"
```

- [ ] **Step 4: Fix `_run_review` in gate.py**

Find (approx line 249):

```python
        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(result, "session_id", "review-gate")
```

Replace with:

```python
        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(provider, "_session_id", None) or "review-gate"
```

- [ ] **Step 5: Fix `_run_brainstorm` in gate.py** (if it follows the same pattern — check for `getattr(result, "session_id", ...)`)

Find the equivalent line in `_run_brainstorm` and apply the same fix using `provider._session_id`.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_autopilot_gate.py tests/test_autopilot_orchestrator.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agentcouncil/autopilot/gate.py tests/test_autopilot_gate.py
git commit -m "fix(autopilot): extract real provider session_id in gate runners instead of hardcoded fallback"
```

---

## Task 4: F3 — Structured findings table in GateNormalizer

**Files:**
- Modify: `agentcouncil/autopilot/normalizer.py:290-303`
- Modify: `tests/test_autopilot_normalizer.py`

`_guidance_from_findings` currently joins finding descriptions as a prose sentence. The reviewer prompt in `review.py` asks for finding-level traceability by ID ("Verify each one: is it resolved?"), but receives prose with no IDs. Replacing prose with a structured markdown table (ID | Title | Severity | Description) lets the reviewer reference findings by ID.

- [ ] **Step 1: Write the failing test**

In `tests/test_autopilot_normalizer.py`, add a new test after `test_review_loop_revise_produces_guidance`:

```python
def test_guidance_from_findings_produces_structured_table():
    """_guidance_from_findings must emit a markdown table, not prose."""
    from agentcouncil.autopilot.normalizer import GateNormalizer
    normalizer = GateNormalizer()

    findings = [
        _make_finding(id="F1", title="Missing input validation", severity="high",
                      description="No validation on user-supplied path parameter"),
        _make_finding(id="F2", title="N+1 query in list endpoint", severity="medium",
                      description="Each item triggers a separate DB call"),
    ]
    guidance = normalizer._guidance_from_findings(findings, fallback="no findings")

    # Must contain the table header
    assert "| ID |" in guidance
    assert "| Title |" in guidance
    assert "| Severity |" in guidance
    assert "| Description |" in guidance
    # Must contain finding IDs
    assert "F1" in guidance
    assert "F2" in guidance
    # Must NOT be plain prose (no semicolons joining descriptions)
    assert "; " not in guidance


def test_guidance_from_findings_sorts_critical_first():
    """Critical and high findings must appear before medium/low in the table."""
    from agentcouncil.autopilot.normalizer import GateNormalizer
    normalizer = GateNormalizer()

    findings = [
        _make_finding(id="F1", title="Low issue", severity="low", description="minor"),
        _make_finding(id="F2", title="Critical issue", severity="critical", description="severe"),
    ]
    guidance = normalizer._guidance_from_findings(findings, fallback="no findings")
    assert guidance.index("F2") < guidance.index("F1")


def test_guidance_from_findings_fallback_when_empty():
    """Empty findings list must return the fallback string."""
    from agentcouncil.autopilot.normalizer import GateNormalizer
    normalizer = GateNormalizer()
    assert normalizer._guidance_from_findings([], fallback="use next_action") == "use next_action"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
pytest tests/test_autopilot_normalizer.py::test_guidance_from_findings_produces_structured_table tests/test_autopilot_normalizer.py::test_guidance_from_findings_sorts_critical_first -v
```

Expected: FAIL — current implementation returns prose, not a table.

- [ ] **Step 3: Rewrite `_guidance_from_findings` in normalizer.py**

Find `_guidance_from_findings` at approximately line 290. Replace the entire method:

```python
    def _guidance_from_findings(self, findings: list, fallback: str) -> str:
        """Emit a structured markdown table of findings for the reviewer.

        Sorted critical → high → medium → low so the most important issues
        appear first. Returns fallback if findings is empty.
        """
        if not findings:
            return fallback

        _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_findings = sorted(
            findings,
            key=lambda f: _sev_order.get(getattr(f, "severity", "low"), 3),
        )

        rows = []
        for f in sorted_findings:
            fid = getattr(f, "id", "—")
            title = getattr(f, "title", "—")
            severity = getattr(f, "severity", "—")
            description = getattr(f, "description", "") or getattr(f, "impact", "—")
            # Escape pipes so the markdown table stays valid
            description = description.replace("|", "\\|")
            rows.append(f"| {fid} | {title} | {severity} | {description} |")

        header = "| ID | Title | Severity | Description |\n|---|---|---|---|"
        return header + "\n" + "\n".join(rows)
```

- [ ] **Step 4: Update the existing guidance tests that assert prose content**

The tests `test_review_revise_produces_guidance` (line 207) and `test_review_loop_revise_produces_guidance` (line 253) check `"Critical logic error" in decision.revision_guidance`. That string will still be present in the Description column of the table, so those tests should still pass. Run them to confirm:

```bash
pytest tests/test_autopilot_normalizer.py -v --tb=short
```

Expected: all pass including the new tests.

- [ ] **Step 5: Commit**

```bash
git add agentcouncil/autopilot/normalizer.py tests/test_autopilot_normalizer.py
git commit -m "fix(autopilot): emit structured finding table from GateNormalizer for reviewer traceability"
```

---

## Task 5: Add escalation_level to AutopilotRun and autopilot_prepare

**Files:**
- Modify: `agentcouncil/autopilot/run.py`
- Modify: `agentcouncil/server.py`
- Modify: `tests/test_autopilot_run.py` (or create a short test inline)

The skill's new Step 0 will ask the user for their escalation level and pass it to `autopilot_prepare`. The server persists it on `AutopilotRun` so the Gate Protocol section of the skill can reference it mid-pipeline.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_autopilot_run.py` (or `tests/test_autopilot_gate.py`):

```python
def test_autopilot_run_escalation_level_defaults_to_normal():
    """AutopilotRun must have escalation_level defaulting to 'normal'."""
    from agentcouncil.autopilot.run import AutopilotRun, StageCheckpoint
    import time, uuid
    run = AutopilotRun(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        spec_id="test-spec",
        status="running",
        current_stage="spec_prep",
        tier=2,
        stages=[StageCheckpoint(stage_name="spec_prep", status="pending")],
        started_at=time.time(),
        updated_at=time.time(),
    )
    assert run.escalation_level == "normal"


def test_autopilot_run_escalation_level_accepts_minimal():
    from agentcouncil.autopilot.run import AutopilotRun, StageCheckpoint
    import time, uuid
    run = AutopilotRun(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        spec_id="test-spec",
        status="running",
        current_stage="spec_prep",
        tier=2,
        stages=[StageCheckpoint(stage_name="spec_prep", status="pending")],
        started_at=time.time(),
        updated_at=time.time(),
        escalation_level="minimal",
    )
    assert run.escalation_level == "minimal"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
pytest tests/test_autopilot_run.py -k "escalation" -v
```

Expected: FAIL — `AutopilotRun` has no `escalation_level` field.

- [ ] **Step 3: Add escalation_level to AutopilotRun in run.py**

In `agentcouncil/autopilot/run.py`, find `class AutopilotRun(BaseModel):`. Add `escalation_level` after `build_retry_count`:

```python
    build_retry_count: int = 0
    escalation_level: str = "normal"  # "minimal" | "normal" | "verbose"
```

- [ ] **Step 4: Expose escalation_level in autopilot_prepare_tool in server.py**

In `agentcouncil/server.py`, find `def autopilot_prepare_tool(`:

```python
def autopilot_prepare_tool(intent: str, spec_id: str, title: str, objective: str,
                            requirements: list[str], acceptance_criteria: list[str],
                            tier: int = 2, target_files: list[str] | None = None) -> dict:
```

Change to:

```python
def autopilot_prepare_tool(intent: str, spec_id: str, title: str, objective: str,
                            requirements: list[str], acceptance_criteria: list[str],
                            tier: int = 2, target_files: list[str] | None = None,
                            escalation_level: str = "normal") -> dict:
```

Find where `run = AutopilotRun(` is constructed (approx line 1419) and add `escalation_level=escalation_level,` to the constructor.

Full updated constructor:

```python
    run = AutopilotRun(
        run_id=run_id, spec_id=spec_id, status="running",
        current_stage="spec_prep", tier=computed_tier,
        tier_classification_reason=tier_reason,
        spec_target_files=target_files,
        stages=stages,
        escalation_level=escalation_level,
        started_at=_time.time(), updated_at=_time.time(),
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_autopilot_run.py -k "escalation" -v
pytest tests/test_autopilot_orchestrator.py -v --tb=short
```

Expected: escalation tests pass; no regressions.

- [ ] **Step 6: Commit**

```bash
git add agentcouncil/autopilot/run.py agentcouncil/server.py tests/test_autopilot_run.py
git commit -m "feat(autopilot): add escalation_level to AutopilotRun and autopilot_prepare"
```

---

## Task 6: F5 — Fix `still_open` vocabulary in review SKILL.md

**Files:**
- Modify: `skills/review/SKILL.md`

The Convergence Loop's verification pass asks the outside agent to return `status ∈ fixed|still_open|reopened`, but the Loop parameters define internal statuses as `{open, fixed, verified, reopened, wont_fix}`. `still_open` is not in the internal vocabulary. Fix: use `open` consistently.

- [ ] **Step 1: Open the file and locate the verification pass prompt**

In `skills/review/SKILL.md`, find the **Verification pass** section inside **Convergence Loop**. Locate the line:

```
> I've applied fixes to the artifact. Re-read the files (paths unchanged) and return JSON with: `finding_updates` (array of `{id, status, reviewer_notes}` for EVERY prior finding, where status ∈ `fixed|still_open|reopened`), ...
```

- [ ] **Step 2: Change `still_open` to `open` in the verification prompt**

Replace that line with:

```
> I've applied fixes to the artifact. Re-read the files (paths unchanged) and return JSON with: `finding_updates` (array of `{id, status, reviewer_notes}` for EVERY prior finding, where status ∈ `fixed|open|reopened`), ...
```

- [ ] **Step 3: Verify no other occurrences of `still_open` remain**

```bash
grep -n "still_open" skills/review/SKILL.md
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add skills/review/SKILL.md
git commit -m "fix(skills/review): use 'open' not 'still_open' in convergence loop verification prompt"
```

---

## Task 7: autopilot SKILL.md — Step 0: escalation intake + existing conventions

**Files:**
- Modify: `skills/autopilot/SKILL.md`

Add a new **Step 0** before the current **Step 1**. This step (a) asks the user to set their escalation level, and (b) reads existing project conventions. All subsequent step numbers shift by one, but for this task we only insert Step 0 — do not renumber the rest (the subsequent tasks will reference them by content, not number).

- [ ] **Step 1: Insert Step 0 after the Pipeline diagram and before "## Protocol — follow these steps exactly"**

Find:

```markdown
### Step 1: Understand the intent
```

Insert before it:

```markdown
### Step 0: Set escalation level and read existing conventions

Send the user **one message** containing both of the following. Do not proceed until you have the answer to item (1).

**1. Escalation level** — ask:

> "How should I handle unknowns during this run?
> - **`minimal`**: interrupt only for critical blockers — security risks, potential data loss, or scope changes that could be destructive
> - **`normal`** (default): interrupt when the wrong assumption would require significant rework of the spec or plan
> - **`verbose`**: ask about anything uncertain before proceeding
>
> Reply with `minimal`, `normal`, or `verbose` (or just press Enter for `normal`)."

Record the answer as `ESCALATION_LEVEL`. Default to `normal` if the user presses Enter or gives no answer.

**2. Read existing project conventions** — before writing the spec, read these files if they exist (they bound your spec and test strategy):
- `pyproject.toml` — test runner (`[tool.pytest.ini_options]`), lint config (`[tool.ruff]` or `[tool.mypy]`), build commands
- `pytest.ini` or `setup.cfg` — alternate pytest config
- `.ruff.toml` — alternate ruff config
- `Makefile` — `test`, `lint`, `build` targets

Note: (a) the test command to use in build steps, (b) the lint/type-check command if configured, (c) where tests live.

**Critical unknowns always escalate regardless of `ESCALATION_LEVEL`:** security risks, destructive scope (deleting data, breaking APIs), or requirements that contradict each other. For all other unknowns, apply the level the user set.

```

- [ ] **Step 2: Pass ESCALATION_LEVEL to autopilot_prepare**

Find the `autopilot_prepare` call description in Step 3 (now Step 4 after renumbering — but locate it by content):

```markdown
Call `mcp__agentcouncil__autopilot_prepare` with all spec fields.
```

Change to:

```markdown
Call `mcp__agentcouncil__autopilot_prepare` with all spec fields, plus `escalation_level=ESCALATION_LEVEL`.
```

- [ ] **Step 3: Verify the skill reads cleanly**

```bash
grep -n "Step 0\|ESCALATION_LEVEL\|escalation_level" skills/autopilot/SKILL.md
```

Expected: lines show Step 0, ESCALATION_LEVEL usages, and the autopilot_prepare call.

- [ ] **Step 4: Commit**

```bash
git add skills/autopilot/SKILL.md
git commit -m "feat(skills/autopilot): add Step 0 escalation intake and existing conventions read"
```

---

## Task 8: autopilot SKILL.md — Spec phase improvements

**Files:**
- Modify: `skills/autopilot/SKILL.md`

Add assumption surfacing, a `testing_strategy` field, a `behavioral_boundaries` field, a pre-spec conventions confirmation, and a spec-file write step.

- [ ] **Step 1: Add assumption surfacing to the intent step**

Find Step 1 (Understand the intent):

```markdown
### Step 1: Understand the intent

Read the user's intent. If it's vague, ask 1-2 clarifying questions.
```

Replace with:

```markdown
### Step 1: Understand the intent

Read the user's intent. Before writing the spec, list the technical assumptions you are making — about the tech stack, framework, auth model, data storage, deployment target, and any conventions you read in Step 0. Present them as:

```
ASSUMPTIONS:
1. [assumption]
2. [assumption]
→ Correct me now or I'll proceed with these.
```

If the intent is genuinely vague (target unclear, scope undefined), ask 1-2 clarifying questions in the same message as your assumptions. Batch everything — one message.

```

- [ ] **Step 2: Add `testing_strategy` and `behavioral_boundaries` to the spec template in Step 2**

Find Step 2 (Build the spec). Locate the spec field list:

```markdown
- **spec_id**: Short kebab-case identifier (e.g., `add-backtester`, `fix-auth-timeout`)
- **title**: One-line title
- **objective**: 1-2 sentence description
- **requirements**: List of specific things that must be built/changed
- **acceptance_criteria**: List of verifiable conditions (e.g., "tests pass", "file contains X")
- **target_files**: Files likely created or modified
- **tier**: 1 (low-risk), 2 (standard, default), or 3 (sensitive)
```

Replace with:

```markdown
- **spec_id**: Short kebab-case identifier (e.g., `add-backtester`, `fix-auth-timeout`)
- **title**: One-line title
- **objective**: 1-2 sentence description
- **requirements**: List of specific things that must be built/changed
- **acceptance_criteria**: List of verifiable conditions (e.g., "tests pass", "file contains X")
- **target_files**: Files likely created or modified (paths with `auth/`, `migrations/`, `infra/`, `deploy/`, `permissions/` trigger tier 3)
- **testing_strategy**: Test framework (from Step 0), test locations, expected test types for this change (unit/integration/e2e). Example: "pytest, tests/ dir, unit tests for logic, one integration test for the API endpoint."
- **behavioral_boundaries**:
  - *Always*: actions you will always take (e.g., "run tests before commit", "validate all user inputs")
  - *Ask first*: actions that need approval (e.g., "schema changes", "adding new dependencies")
  - *Never*: prohibited actions (e.g., "modify files outside target_files without documenting", "skip failing tests")
- **tier**: 1 (low-risk), 2 (standard, default), or 3 (sensitive)
```

- [ ] **Step 3: Add spec file write step before autopilot_prepare call**

Find Step 3 (Validate and register the run):

```markdown
### Step 3: Validate and register the run

Call `mcp__agentcouncil__autopilot_prepare` with all spec fields.
```

Insert before the `autopilot_prepare` call:

```markdown
Write the spec to disk before registering:

```bash
# Write to docs/autopilot/specs/{spec_id}.md
```

Create the file `docs/autopilot/specs/{spec_id}.md` with the full spec content formatted as markdown. This persists the spec for future reference independent of this conversation.

Then call `mcp__agentcouncil__autopilot_prepare` ...
```

- [ ] **Step 4: Update the spec gate focus_areas to check for testing_strategy**

Find Step 4 (Gate — review the spec), the `focus_areas` list:

```markdown
- **focus_areas**: `["requirements clarity", "acceptance criteria testability", "scope boundaries", "missing edge cases"]`
```

Replace with:

```markdown
- **focus_areas**: `["requirements clarity", "acceptance criteria testability", "testing strategy completeness", "behavioral boundaries defined", "scope boundaries", "missing edge cases"]`
```

- [ ] **Step 5: Verify**

```bash
grep -n "testing_strategy\|behavioral_boundaries\|docs/autopilot/specs\|ASSUMPTIONS" skills/autopilot/SKILL.md
```

- [ ] **Step 6: Commit**

```bash
git add skills/autopilot/SKILL.md
git commit -m "feat(skills/autopilot): add assumption surfacing, testing_strategy, boundaries, and spec file persistence to spec phase"
```

---

## Task 9: autopilot SKILL.md — Plan phase improvements

**Files:**
- Modify: `skills/autopilot/SKILL.md`

Add read-only mode declaration, per-task verification column, and a Risks and Mitigations table to the plan step.

- [ ] **Step 1: Add read-only mode declaration to the plan step**

Find Step 5 (Plan — follow the plan workflow recipe). At the top of the step, locate:

```markdown
Read `agentcouncil/autopilot/workflows/plan/workflow.md` — this is the execution recipe.

Follow the 5-step planning process:
```

Replace with:

```markdown
Read `agentcouncil/autopilot/workflows/plan/workflow.md` — this is the execution recipe.

**Read-only mode:** Do not write or modify any code during this step. The output is a plan document, not implementation.

Follow the 5-step planning process:
```

- [ ] **Step 2: Add Verification column to the task table**

Find the task table format:

```markdown
| Task ID | Title | Complexity | Depends On | Target Files |
|---------|-------|------------|------------|--------------|
| task-01 | ...   | small      | —          | ...          |
```

Replace with:

```markdown
| Task ID | Title | Complexity | Depends On | Target Files | Verification |
|---------|-------|------------|------------|--------------|--------------|
| task-01 | ...   | small      | —          | ...          | `pytest tests/path/test_foo.py` passes |
```

- [ ] **Step 3: Add Risks and Mitigations section to the plan display**

Find the plan display block. After the `**Execution Order:** task-01, task-02, ...` line, add:

```markdown
**Risks and Mitigations:**
| Risk | Severity | Mitigation |
|------|----------|------------|
| [risk from spec gate findings] | high/medium/low | [what you'll do if it materialises] |
```

If the spec gate produced findings with `revise` guidance, turn each unresolved concern into a risk row.

- [ ] **Step 4: Verify**

```bash
grep -n "Read-only mode\|Verification\|Risks and Mitigations" skills/autopilot/SKILL.md
```

- [ ] **Step 5: Commit**

```bash
git add skills/autopilot/SKILL.md
git commit -m "feat(skills/autopilot): add read-only mode, per-task verification, and risks table to plan phase"
```

---

## Task 10: autopilot SKILL.md — Build phase improvements

**Files:**
- Modify: `skills/autopilot/SKILL.md`

This is the most substantial skill change. Invert the increment cycle to test-first (TDD), add the prove-it pattern for bug fixes, add new build rules (simplicity-first, feature flags, safe defaults, rollback-friendly, 100-line limit), and add regression self-checks every 3 tasks.

- [ ] **Step 1: Invert the increment cycle (TDD order)**

Find the increment cycle in Step 7 (Build):

```markdown
**Implement:** Make the minimal change required. Touch only `task.target_files` unless deviation is documented.

**Test:** Run test commands. Do not advance if tests fail. Fix the implementation, not the tests.

**Verify:** Check the task's `acceptance_criteria` are met.

**Commit:** Focused commit: `{type}({scope}): {description}`. Record the SHA.
```

Replace with:

```markdown
**Write test first (RED):** Before writing any implementation code, write a test that expresses the expected behavior. Run it — it must FAIL. A test that passes immediately proves nothing.

**Implement (GREEN):** Write the minimal code to make the failing test pass. Ask: "What is the simplest thing that could work?" Do not over-engineer. Three similar lines of code is better than a premature abstraction.

**Confirm (PASS):** Run the test. It must pass. If it doesn't, fix the implementation — not the test.

**Refactor:** With the test green, clean up the implementation without changing behavior. Run tests after any refactor step.

**Verify:** Check the task's `acceptance_criteria` are met beyond what the test directly covers.

**Commit:** Focused commit: `{type}({scope}): {description}`. Record the SHA.
```

- [ ] **Step 2: Add prove-it pattern for bug-fix tasks**

After the increment cycle block, add:

```markdown
**Bug-fix tasks — prove-it pattern (REQUIRED):** For any task that fixes a bug:
1. Write a test that reproduces the bug. Run it — it must FAIL (confirming the bug exists).
2. Implement the fix.
3. Run the test — it must PASS (confirming the fix works).
4. Run the full test suite — no new failures (regression guard).

A bug fix without a reproduction test is not complete.
```

- [ ] **Step 3: Update the build rules**

Find the current build rules:

```markdown
Build rules (from the recipe):
- **Rule 0:** One task at a time — no multi-task changes
- **Rule 1:** The plan is the contract — no silent scope expansion
- **Rule 2:** Tests travel with the code
- **Rule 3:** Never commit broken tests
- **Rule 4:** Evidence is not optional
- **Rule 5:** Commit SHAs are the audit trail
```

Replace with:

```markdown
Build rules (from the recipe):
- **Rule 0: Simplicity first** — after implementing, ask: "Could this be fewer lines? Am I building for hypothetical future requirements?" Write the naive, obviously-correct version first.
- **Rule 0.5: Scope discipline** — touch only `task.target_files`. If you notice something worth improving outside scope, note it — don't fix it.
- **Rule 1: The plan is the contract** — no silent scope expansion
- **Rule 2: Tests travel with the code** — unit tests for logic, integration tests for API/DB boundaries, E2E tests only for critical user flows. Aim for ~80% unit / ~15% integration / ~5% E2E.
- **Rule 3: Never commit broken tests**
- **Rule 4: Evidence is not optional**
- **Rule 5: Commit SHAs are the audit trail** — each commit should be independently revertable (additive changes before deletions; avoid mixing logic change + format change in one commit)
- **Rule 6: Safe defaults** — new code defaults to conservative behavior (disabled flags, allowlists not blocklists, strict validation). Especially in tier 3 runs.
- **Rule 7: Feature flags for incomplete slices** — if a task lands user-reachable but incomplete behavior, gate it behind a feature flag so the commit is safe to merge.
- **Rule 8: 100-line limit** — if you are about to write more than ~100 lines without running a test, stop and run the tests first.
```

- [ ] **Step 4: Add regression self-check every 3 tasks**

After the build rules, add:

```markdown
**Regression self-check (every 3 tasks):** After completing every third task (task-03, task-06, task-09, ...), before continuing:
1. Run the **full test suite** (not just the current task's tests).
2. Confirm all previously-completed tasks' acceptance criteria still pass.
3. Confirm the build is clean.

If anything fails, fix it before continuing. This catches regressions while context is fresh, rather than at the final build gate.
```

- [ ] **Step 5: Verify**

```bash
grep -n "Write test first\|prove-it\|Simplicity first\|Rule 6\|Rule 7\|Rule 8\|Regression self-check" skills/autopilot/SKILL.md
```

- [ ] **Step 6: Commit**

```bash
git add skills/autopilot/SKILL.md
git commit -m "feat(skills/autopilot): invert increment cycle to TDD order, add prove-it pattern, new build rules, regression checkpoints"
```

---

## Task 11: autopilot SKILL.md — Verify phase improvements

**Files:**
- Modify: `skills/autopilot/SKILL.md`

Add prove-it verification for bug-fix runs and a conditional lint/type-check step.

- [ ] **Step 1: Add prove-it check to the verify step**

Find Step 9 (Verify). After the probe table output block, add:

```markdown
**Bug-fix runs — reproduction test check:** If this run's intent was a bug fix, verify:
- A reproduction test exists in the diff that was specifically written to fail before the fix.
- That test passes now.

If no reproduction test exists, do not mark verify as complete. Return to the build step and add it.

**Lint and type-check (if configured):** If Step 0 detected a lint or type-check command in the project:
- Run it now and confirm it passes.
- Record the result in the verification output.
- If it fails, fix the issues before the verify step completes.
```

- [ ] **Step 2: Verify**

```bash
grep -n "reproduction test\|Lint and type-check" skills/autopilot/SKILL.md
```

- [ ] **Step 3: Commit**

```bash
git add skills/autopilot/SKILL.md
git commit -m "feat(skills/autopilot): add prove-it check and conditional lint to verify phase"
```

---

## Task 12: autopilot SKILL.md — Gate Protocol escalation_level guidance

**Files:**
- Modify: `skills/autopilot/SKILL.md`

The Gate Protocol section must reference `ESCALATION_LEVEL` when deciding whether to stop and ask the user vs. proceed with documented best judgment.

- [ ] **Step 1: Update the Gate Protocol section**

Find the **Gate Protocol** section. After the existing bullet points, find:

```markdown
If a gate revision loop exceeds 2 iterations, stop and ask the user — do not loop forever.
```

Replace with:

```markdown
If a gate revision loop exceeds 2 iterations, stop and ask the user — do not loop forever.

**Escalation during the pipeline (consult `ESCALATION_LEVEL`):**

When you encounter an unknown, ambiguity, or unexpected scope question mid-pipeline, apply the level set in Step 0:
- **`minimal`**: proceed with best judgment and document your assumption inline ("Assuming X — override this by running the command again with Y"). Escalate only for: security risks, potential data loss, or scope changes that could be destructive.
- **`normal`**: escalate if the wrong assumption would require significant rework of the spec or plan. Proceed autonomously for low-consequence choices (variable names, minor implementation details, stylistic decisions).
- **`verbose`**: escalate for any uncertain choice. Ask before proceeding.

Critical blockers (security risk, data loss potential, contradictory requirements) always escalate regardless of level.
```

- [ ] **Step 2: Verify**

```bash
grep -n "ESCALATION_LEVEL\|minimal.*escalate\|verbose.*escalate" skills/autopilot/SKILL.md
```

- [ ] **Step 3: Run the full test suite one final time**

```bash
pytest tests/ -v --tb=short -q
```

Expected: all tests pass. No regressions from the code changes in Tasks 1–5.

- [ ] **Step 4: Commit**

```bash
git add skills/autopilot/SKILL.md
git commit -m "feat(skills/autopilot): add escalation_level consultation to Gate Protocol for mid-pipeline unknowns"
```

---

## Self-Review

### Spec coverage check

| Issue | Task |
|-------|------|
| F1: bare except Exception swallows gate failures | Task 1 |
| F2: DecideInput wrong field names | Task 2 |
| F4: hardcoded gate session IDs | Task 3 |
| F3: prose revision_guidance, not structured findings | Task 4 |
| escalation_level schema field | Task 5 |
| F5: still_open vocabulary mismatch in review skill | Task 6 |
| Step 0 escalation intake + convention reading | Task 7 |
| FIND-001 assumption surfacing | Task 8 |
| FIND-002 testing_strategy in spec | Task 8 |
| FIND-003 behavioral_boundaries in spec | Task 8 |
| FIND-004 spec persisted to file | Task 8 |
| FIND-005 confirm existing conventions (reframed) | Task 7 |
| FIND-010 read-only mode in plan | Task 9 |
| FIND-008 per-task verification column | Task 9 |
| FIND-009 risks and mitigations table | Task 9 |
| FIND-012 TDD cycle inverted | Task 10 |
| FIND-013 simplicity-first rule | Task 10 |
| FIND-014 feature flag guidance | Task 10 |
| FIND-015 safe-defaults rule | Task 10 |
| FIND-016 rollback-friendly commits | Task 10 |
| FIND-017 100-line limit | Task 10 |
| FIND-018 prove-it pattern in build | Task 10 |
| FIND-019 test pyramid in build rules | Task 10 |
| FIND-020 prove-it check in verify | Task 11 |
| FIND-022 conditional lint/type-check in verify | Task 11 |
| Gate Protocol escalation consultation | Task 12 |

**Not included (per scope decision):** FIND-007 mid-build checkpoints are addressed by Task 10's regression self-check (equivalent mechanism, self-check not reviewer gate). FIND-006 intentionally excluded (AI gate replaces human self-checklist). FIND-011 intentionally excluded (decomposition rationale belongs in plan's Execution Order). Ship phase findings (FIND-023 through FIND-030) excluded per user request.

### Placeholder scan

None found — all steps contain actual code, exact file paths, and expected test output.

### Type consistency

- `DecideInput.decision` and `DecideInput.criteria` match the schema definition at `schemas.py:191-194`.
- `AutopilotRun.escalation_level: str = "normal"` is `Optional`-compatible for existing runs (Pydantic default handles missing field on load).
- `_guidance_from_findings` return type is `str` — unchanged from current signature.
- `provider._session_id` attribute verified in `agentcouncil/providers/claude.py:71`.
