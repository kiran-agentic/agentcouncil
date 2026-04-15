"""agentcouncil.autopilot.router — Rule-based tier router and dynamic tier promotion.

Implements SAFE-03 (pre-run tier classification) and SAFE-04 (mid-run tier promotion):

- SAFE-03: classify_run inspects SpecArtifact.target_files against SENSITIVE_PATH_PATTERNS
  and assigns the initial AutopilotRun tier before execution begins.
- SAFE-04: detect_undeclared_sensitive_files identifies sensitive paths that appear during
  execution but were not declared in the original spec, triggering tier promotion.

Tier promotion is strictly monotonic (max operation) — no silent demotion.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentcouncil.autopilot.artifacts import SpecArtifact

# ---------------------------------------------------------------------------
# Sensitive path patterns (canonical list — imported by prep.py)
# ---------------------------------------------------------------------------

#: Canonical list of sensitive path patterns for tier classification.
#: prep.py imports this list and appends ".env" for its own codebase scan.
SENSITIVE_PATH_PATTERNS: list[str] = [
    "auth",
    "migrations",
    "infra",
    "deploy",
    "permissions",
]


# ---------------------------------------------------------------------------
# SAFE-03: Initial run tier classification
# ---------------------------------------------------------------------------


def classify_run(spec: "SpecArtifact", requested_tier: int = 2) -> tuple[int, str]:
    """Classify a run's initial tier based on declared target_files (SAFE-03).

    Checks each path in spec.target_files against SENSITIVE_PATH_PATTERNS
    (case-insensitive). On the first sensitive match, returns (3, reason).
    If no sensitive paths are found, returns (requested_tier, reason) — never
    demotes below the caller-supplied tier.

    Args:
        spec: SpecArtifact whose target_files declare the implementation intent.
        requested_tier: Tier requested by the caller (default 2). Only promoted,
            never demoted.

    Returns:
        Tuple of (tier: int, reason: str) where tier is 1/2/3 and reason is
        a loggable string explaining the classification decision.
    """
    for path in spec.target_files:
        path_lower = path.lower()
        for pattern in SENSITIVE_PATH_PATTERNS:
            if pattern in path_lower:
                return 3, (
                    f"target_files contains sensitive path: {path!r} matches pattern {pattern!r}"
                )
    # Clamp to valid tier range (FM-06)
    clamped = max(1, min(3, requested_tier))
    return clamped, "no sensitive paths detected in target_files"


# ---------------------------------------------------------------------------
# SAFE-04: Mid-run undeclared sensitive file detection
# ---------------------------------------------------------------------------


def detect_undeclared_sensitive_files(
    declared_paths: list[str],
    actual_paths: list[str],
) -> list[str]:
    """Return sensitive paths in actual_paths that were not covered by declared_paths (SAFE-04).

    A sensitive pattern is "covered" if at least one path in declared_paths contains
    that pattern. This means if the spec declared "src/auth/login.py", any other auth
    path that appears at runtime is still considered declared (the pattern was known).

    Args:
        declared_paths: Paths declared in the spec (SpecArtifact.target_files or
            equivalent). Used to determine which sensitive patterns were pre-declared.
        actual_paths: Paths actually touched during execution (e.g., BuildArtifact.files_changed).

    Returns:
        List of paths from actual_paths that contain a sensitive pattern not covered
        by any path in declared_paths. Empty list if no undeclared sensitive paths found.
    """
    # Determine which sensitive patterns are already covered by declared paths
    declared_patterns: set[str] = set()
    for path in declared_paths:
        path_lower = path.lower()
        for pattern in SENSITIVE_PATH_PATTERNS:
            if pattern in path_lower:
                declared_patterns.add(pattern)

    # Find actual paths that contain a sensitive pattern NOT in declared_patterns
    undeclared: list[str] = []
    for path in actual_paths:
        path_lower = path.lower()
        for pattern in SENSITIVE_PATH_PATTERNS:
            if pattern in path_lower and pattern not in declared_patterns:
                undeclared.append(path)
                break  # Only add each path once even if it matches multiple patterns

    return undeclared


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = ["classify_run", "detect_undeclared_sensitive_files", "SENSITIVE_PATH_PATTERNS"]
