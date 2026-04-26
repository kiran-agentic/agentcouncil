"""Regression checks for the public /autopilot protocol instructions."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_autopilot_skill_requires_resume_guard_and_checkpoint_tool():
    text = (ROOT / "skills/autopilot/SKILL.md").read_text()

    assert "docs/autopilot/active-run.json" in text
    assert "Mandatory resume guard" in text
    assert "mcp__agentcouncil__autopilot_checkpoint" in text
    assert "backend=<profile>" in text
    assert "challenge_backend=<profile>" in text
    assert "review_depth=<legacy|fast|balanced|deep>" in text
    assert "lead_review_model=<model>" in text
    assert "mcp__agentcouncil__autopilot_context_pack" in text
    assert "review_context" in text
    assert "review_backend=REVIEW_BACKEND" in text
    assert "backend**: `REVIEW_BACKEND` if set" in text
    assert "backend**: `CHALLENGE_BACKEND` if set" in text
    assert "required_tool" in text
    assert "Gates are NEVER optional" in text


def test_autopilot_skill_requires_build_artifact_before_build_gate():
    text = (ROOT / "skills/autopilot/SKILL.md").read_text()

    build_artifact_idx = text.index("Then produce a formal `BuildArtifact`")
    build_gate_idx = text.index("### Step 8: Gate — review the build")
    verify_idx = text.index("### Step 9: Verify")

    assert build_artifact_idx < build_gate_idx < verify_idx
    assert 'protocol_step**: `"build_complete"`' in text
    assert 'protocol_step="build_review_passed"' in text


def test_build_workflow_forbids_verify_before_build_review_checkpoint():
    text = (ROOT / "agentcouncil/autopilot/workflows/build/workflow.md").read_text()

    assert "Final Build Handoff" in text
    assert 'protocol_step="build_complete"' in text
    assert 'protocol_step="build_review_passed"' in text
    assert "Do not start verification until the build review gate has passed" in text
