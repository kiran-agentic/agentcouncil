from __future__ import annotations

from typing import Any, Literal

from agentcouncil.schemas import (
    ChallengeArtifact,
    ConsensusArtifact,
    ConvergenceResult,
    DecideArtifact,
    ReviewArtifact,
)
from agentcouncil.autopilot.artifacts import GateDecision

__all__ = ["GateNormalizer"]

_VALID_PROTOCOL_TYPES: tuple[str, ...] = (
    "brainstorm",
    "review",
    "review_loop",
    "challenge",
    "decide",
)


class GateNormalizer:
    """Translates any of the five protocol output types into a uniform GateDecision.

    The orchestrator never branches on protocol type — it calls normalize() and
    acts on the returned decision (advance / revise / block).
    """

    def normalize(
        self,
        protocol_type: str,
        artifact: Any,
        session_id: str = "unknown",
    ) -> GateDecision:
        """Normalize a protocol artifact to a GateDecision.

        Always returns a GateDecision — never raises. Unknown protocol types and
        mismatched artifact types produce decision="block" with a descriptive rationale.
        """
        try:
            return self._dispatch(protocol_type, artifact, session_id)
        except Exception as exc:  # noqa: BLE001
            safe_type = (
                protocol_type
                if protocol_type in _VALID_PROTOCOL_TYPES
                else "brainstorm"
            )
            return GateDecision(
                decision="block",
                protocol_type=safe_type,  # type: ignore[arg-type]
                protocol_session_id=session_id,
                rationale=(
                    f"GateNormalizer caught an unexpected error while normalizing "
                    f"protocol_type={protocol_type!r}: {exc}"
                ),
            )

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        protocol_type: str,
        artifact: Any,
        session_id: str,
    ) -> GateDecision:
        if protocol_type == "brainstorm":
            if not isinstance(artifact, ConsensusArtifact):
                raise TypeError(
                    f"brainstorm protocol expects ConsensusArtifact, got "
                    f"{type(artifact).__name__}"
                )
            return self._normalize_brainstorm(artifact, session_id)

        if protocol_type == "review":
            if not isinstance(artifact, ReviewArtifact):
                raise TypeError(
                    f"review protocol expects ReviewArtifact, got "
                    f"{type(artifact).__name__}"
                )
            return self._normalize_review(artifact, session_id)

        if protocol_type == "review_loop":
            if not isinstance(artifact, ConvergenceResult):
                raise TypeError(
                    f"review_loop protocol expects ConvergenceResult, got "
                    f"{type(artifact).__name__}"
                )
            return self._normalize_review_loop(artifact, session_id)

        if protocol_type == "challenge":
            if not isinstance(artifact, ChallengeArtifact):
                raise TypeError(
                    f"challenge protocol expects ChallengeArtifact, got "
                    f"{type(artifact).__name__}"
                )
            return self._normalize_challenge(artifact, session_id)

        if protocol_type == "decide":
            if not isinstance(artifact, DecideArtifact):
                raise TypeError(
                    f"decide protocol expects DecideArtifact, got "
                    f"{type(artifact).__name__}"
                )
            return self._normalize_decide(artifact, session_id)

        raise ValueError(f"Unrecognized protocol_type: {protocol_type!r}")

    # ------------------------------------------------------------------
    # Per-protocol handlers
    # ------------------------------------------------------------------

    def _normalize_brainstorm(
        self, artifact: ConsensusArtifact, session_id: str
    ) -> GateDecision:
        # CRITICAL: use_enum_values=True means artifact.status is a str at runtime.
        # Compare against string literals, NOT enum members.
        if artifact.status in ("consensus", "consensus_with_reservations"):
            return GateDecision(
                decision="advance",
                protocol_type="brainstorm",
                protocol_session_id=session_id,
                rationale=(
                    f"Brainstorm reached {artifact.status}; advancing to next stage."
                ),
            )

        # unresolved_disagreement or partial_failure -> block
        return GateDecision(
            decision="block",
            protocol_type="brainstorm",
            protocol_session_id=session_id,
            rationale=(
                f"Brainstorm status={artifact.status!r} indicates no usable consensus; "
                "blocking until the team resolves disagreements."
            ),
        )

    def _normalize_review(
        self, artifact: ReviewArtifact, session_id: str
    ) -> GateDecision:
        if artifact.verdict == "pass":
            return GateDecision(
                decision="advance",
                protocol_type="review",
                protocol_session_id=session_id,
                rationale="Review passed; no blocking findings.",
            )

        if artifact.verdict == "revise":
            guidance = self._guidance_from_findings(
                artifact.findings, fallback=artifact.next_action
            )
            return GateDecision(
                decision="revise",
                protocol_type="review",
                protocol_session_id=session_id,
                rationale="Review verdict=revise; actionable guidance attached.",
                revision_guidance=guidance,
            )

        # verdict == "escalate" -> block
        return GateDecision(
            decision="block",
            protocol_type="review",
            protocol_session_id=session_id,
            rationale=(
                "Review verdict=escalate; the issue requires escalation before proceeding."
            ),
        )

    def _normalize_review_loop(
        self, artifact: ConvergenceResult, session_id: str
    ) -> GateDecision:
        if artifact.final_verdict == "pass":
            return GateDecision(
                decision="advance",
                protocol_type="review_loop",
                protocol_session_id=session_id,
                rationale=(
                    f"Convergence loop exited with final_verdict=pass "
                    f"(exit_reason={artifact.exit_reason!r})."
                ),
            )

        if artifact.final_verdict == "revise":
            guidance = self._guidance_from_findings(
                artifact.final_findings, fallback=artifact.exit_reason
            )
            return GateDecision(
                decision="revise",
                protocol_type="review_loop",
                protocol_session_id=session_id,
                rationale=(
                    f"Convergence loop ended with unresolved findings "
                    f"(exit_reason={artifact.exit_reason!r}); revise required."
                ),
                revision_guidance=guidance,
            )

        # final_verdict == "escalate" -> block
        return GateDecision(
            decision="block",
            protocol_type="review_loop",
            protocol_session_id=session_id,
            rationale=(
                "Convergence loop final_verdict=escalate; escalation required "
                "before proceeding."
            ),
        )

    def _normalize_challenge(
        self, artifact: ChallengeArtifact, session_id: str
    ) -> GateDecision:
        if artifact.readiness == "ready":
            return GateDecision(
                decision="advance",
                protocol_type="challenge",
                protocol_session_id=session_id,
                rationale="Challenge readiness=ready; system passed adversarial review.",
            )

        if artifact.readiness == "needs_hardening":
            must_harden = [
                fm for fm in artifact.failure_modes if fm.disposition == "must_harden"
            ]
            guidance = "; ".join(fm.description for fm in must_harden) if must_harden else (
                "Hardening required but no specific failure modes flagged."
            )
            return GateDecision(
                decision="revise",
                protocol_type="challenge",
                protocol_session_id=session_id,
                rationale=(
                    "Challenge readiness=needs_hardening; must-harden failure modes attached."
                ),
                revision_guidance=guidance,
            )

        # readiness == "not_ready" -> block
        return GateDecision(
            decision="block",
            protocol_type="challenge",
            protocol_session_id=session_id,
            rationale=(
                "Challenge readiness=not_ready; system is not ready to proceed."
            ),
        )

    def _normalize_decide(
        self, artifact: DecideArtifact, session_id: str
    ) -> GateDecision:
        if artifact.outcome == "decided":
            return GateDecision(
                decision="advance",
                protocol_type="decide",
                protocol_session_id=session_id,
                rationale=(
                    f"Decision reached: winner_option_id={artifact.winner_option_id!r}."
                ),
            )

        if artifact.outcome == "experiment":
            return GateDecision(
                decision="revise",
                protocol_type="decide",
                protocol_session_id=session_id,
                rationale="Decision outcome=experiment; experiment plan attached.",
                revision_guidance=artifact.experiment_plan,
            )

        # outcome == "deferred" -> block
        return GateDecision(
            decision="block",
            protocol_type="decide",
            protocol_session_id=session_id,
            rationale=(
                f"Decision deferred: {artifact.defer_reason or 'no reason given'}."
            ),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
            description = description.replace("|", "\\|")
            rows.append(f"| {fid} | {title} | {severity} | {description} |")

        header = "| ID | Title | Severity | Description |\n|---|---|---|---|"
        return header + "\n" + "\n".join(rows)
