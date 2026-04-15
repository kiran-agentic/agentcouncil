"""Tests for agentcouncil/autopilot/router.py — SAFE-03 and SAFE-04 behaviors.

Covers:
- SAFE-03: classify_run assigns tier=3 for specs with sensitive target_files,
  preserves requested_tier when no sensitive paths detected, never demotes.
- SAFE-04: detect_undeclared_sensitive_files identifies sensitive paths not covered
  by the declared spec paths.
- AutopilotRun.tier_classification_reason field round-trip.
"""
from __future__ import annotations

import json
import time

import pytest

from agentcouncil.autopilot.router import (
    SENSITIVE_PATH_PATTERNS,
    classify_run,
    detect_undeclared_sensitive_files,
)
from agentcouncil.autopilot.artifacts import SpecArtifact
from agentcouncil.autopilot.run import AutopilotRun, StageCheckpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(target_files: list[str]) -> SpecArtifact:
    """Create a minimal valid SpecArtifact with the given target_files."""
    return SpecArtifact(
        spec_id="test-spec",
        title="Test",
        objective="Test objective",
        requirements=["req-1"],
        acceptance_criteria=["ac-1"],
        target_files=target_files,
    )


def _make_run(tier: int = 2, tier_classification_reason: str | None = None) -> AutopilotRun:
    """Create a minimal valid AutopilotRun for field testing."""
    stages = [
        StageCheckpoint(stage_name=name, status="pending")
        for name in ["spec_prep", "plan", "build", "verify", "ship"]
    ]
    return AutopilotRun(
        run_id="test-run-001",
        spec_id="test-spec",
        status="running",
        current_stage="spec_prep",
        tier=tier,
        tier_classification_reason=tier_classification_reason,
        stages=stages,
        started_at=time.time(),
        updated_at=time.time(),
    )


# ---------------------------------------------------------------------------
# TestClassifyRun — SAFE-03
# ---------------------------------------------------------------------------


class TestClassifyRun:
    """Tests for classify_run: initial tier classification from target_files."""

    def test_auth_path_returns_tier3(self):
        """Auth path in target_files should classify as tier=3."""
        spec = _make_spec(["src/auth/login.py"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 3
        assert "auth" in reason

    def test_migrations_path_returns_tier3(self):
        """Migrations path in target_files should classify as tier=3."""
        spec = _make_spec(["db/migrations/001.sql"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 3
        assert "migrations" in reason

    def test_infra_path_returns_tier3(self):
        """Infra path in target_files should classify as tier=3."""
        spec = _make_spec(["infra/terraform/main.tf"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 3
        assert "infra" in reason

    def test_deploy_path_returns_tier3(self):
        """Deploy path in target_files should classify as tier=3 even from tier=1 request."""
        spec = _make_spec(["scripts/deploy/run.sh"])
        tier, reason = classify_run(spec, requested_tier=1)
        assert tier == 3
        assert "deploy" in reason

    def test_permissions_path_returns_tier3(self):
        """Permissions path in target_files should classify as tier=3."""
        spec = _make_spec(["src/permissions/roles.py"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 3
        assert "permissions" in reason

    def test_non_sensitive_path_preserves_requested_tier(self):
        """Non-sensitive path should preserve the requested_tier (no promotion)."""
        spec = _make_spec(["src/utils/helpers.py"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 2
        assert "no sensitive" in reason.lower()

    def test_empty_target_files_preserves_requested_tier(self):
        """Empty target_files should preserve the requested_tier."""
        spec = _make_spec([])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 2
        assert "no sensitive" in reason.lower()

    def test_no_demotion_when_requested_tier_already_3(self):
        """classify_run must not demote tier — if requested=3, result is 3 regardless."""
        spec = _make_spec(["src/utils/helpers.py"])
        tier, reason = classify_run(spec, requested_tier=3)
        assert tier == 3
        # Reason should still reflect the classification (no sensitive paths)
        assert reason is not None

    def test_case_insensitive_pattern_matching(self):
        """Sensitive pattern detection must be case-insensitive."""
        spec = _make_spec(["src/Auth/Login.py"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert tier == 3
        # reason contains auth (lowercase pattern from SENSITIVE_PATH_PATTERNS)
        assert "auth" in reason.lower()

    def test_sensitive_path_reason_contains_path(self):
        """Reason string should include the path that triggered classification."""
        spec = _make_spec(["src/auth/login.py"])
        tier, reason = classify_run(spec, requested_tier=2)
        assert "src/auth/login.py" in reason

    def test_default_requested_tier_is_2(self):
        """Default requested_tier should be 2."""
        spec = _make_spec([])
        tier, reason = classify_run(spec)
        assert tier == 2

    def test_sensitive_path_patterns_exported(self):
        """SENSITIVE_PATH_PATTERNS must be exported from router module."""
        assert "auth" in SENSITIVE_PATH_PATTERNS
        assert "migrations" in SENSITIVE_PATH_PATTERNS
        assert "infra" in SENSITIVE_PATH_PATTERNS
        assert "deploy" in SENSITIVE_PATH_PATTERNS
        assert "permissions" in SENSITIVE_PATH_PATTERNS
        # .env is intentionally NOT in the router's list (it belongs to prep.py)
        assert ".env" not in SENSITIVE_PATH_PATTERNS


# ---------------------------------------------------------------------------
# TestDetectUndeclaredSensitiveFiles — SAFE-04
# ---------------------------------------------------------------------------


class TestDetectUndeclaredSensitiveFiles:
    """Tests for detect_undeclared_sensitive_files: promotion trigger detection."""

    def test_declared_auth_pattern_covers_all_auth_paths(self):
        """If auth was declared, all auth paths in actual should be considered covered."""
        declared = ["src/auth/login.py"]
        actual = ["src/auth/login.py", "src/auth/utils.py"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert result == []

    def test_undeclared_auth_path_returned(self):
        """Auth path in actual not covered by declared patterns should be returned."""
        declared = ["src/utils.py"]
        actual = ["src/auth/login.py"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert "src/auth/login.py" in result

    def test_non_sensitive_actual_path_not_returned(self):
        """Non-sensitive paths in actual should never appear in result."""
        declared = ["src/utils.py"]
        actual = ["src/utils.py"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert result == []

    def test_multiple_undeclared_sensitive_paths_all_returned(self):
        """Multiple undeclared sensitive paths should all be in the result."""
        declared = []
        actual = ["infra/main.tf", "deploy/run.sh"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert "infra/main.tf" in result
        assert "deploy/run.sh" in result

    def test_declared_infra_pattern_covers_different_infra_path(self):
        """Declaring one infra path should cover all infra paths in actual."""
        declared = ["infra/old.tf"]
        actual = ["infra/new.tf"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert result == []

    def test_empty_declared_empty_actual_returns_empty(self):
        """Both empty lists should return empty result."""
        result = detect_undeclared_sensitive_files([], [])
        assert result == []

    def test_empty_declared_with_sensitive_actual_returns_undeclared(self):
        """No declared paths means all sensitive actuals are undeclared."""
        declared = []
        actual = ["src/permissions/roles.py"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert "src/permissions/roles.py" in result

    def test_path_with_multiple_patterns_added_once(self):
        """A path matching multiple patterns should appear only once in result."""
        # Hypothetical path that would match both 'auth' and 'permissions'
        declared = []
        actual = ["src/auth-permissions/x.py"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert result.count("src/auth-permissions/x.py") == 1

    def test_declared_auth_does_not_cover_deploy(self):
        """Declaring auth should not cover deploy paths."""
        declared = ["src/auth/login.py"]
        actual = ["deploy/run.sh"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert "deploy/run.sh" in result

    def test_case_insensitive_actual_path_detection(self):
        """Sensitive pattern detection in actual paths should be case-insensitive."""
        declared = []
        actual = ["src/Auth/Login.py"]
        result = detect_undeclared_sensitive_files(declared, actual)
        assert "src/Auth/Login.py" in result


# ---------------------------------------------------------------------------
# TestTierClassificationReason — AutopilotRun field
# ---------------------------------------------------------------------------


class TestTierClassificationReason:
    """Tests for AutopilotRun.tier_classification_reason field."""

    def test_field_can_be_set_on_construction(self):
        """AutopilotRun should accept tier_classification_reason on construction."""
        run = _make_run(tier=3, tier_classification_reason="auth detected")
        assert run.tier_classification_reason == "auth detected"

    def test_field_defaults_to_none(self):
        """AutopilotRun constructed without tier_classification_reason has it as None."""
        run = _make_run()
        assert run.tier_classification_reason is None

    def test_field_round_trips_through_json(self):
        """tier_classification_reason should survive JSON serialization round-trip."""
        run = _make_run(tier=3, tier_classification_reason="some reason")
        json_str = run.model_dump_json()
        loaded = AutopilotRun.model_validate_json(json_str)
        assert loaded.tier_classification_reason == "some reason"

    def test_none_round_trips_through_json(self):
        """tier_classification_reason=None should survive JSON round-trip."""
        run = _make_run()
        json_str = run.model_dump_json()
        loaded = AutopilotRun.model_validate_json(json_str)
        assert loaded.tier_classification_reason is None

    def test_field_present_in_model_dump(self):
        """tier_classification_reason should be present in model_dump output."""
        run = _make_run(tier_classification_reason="test reason")
        data = run.model_dump()
        assert "tier_classification_reason" in data
        assert data["tier_classification_reason"] == "test reason"
