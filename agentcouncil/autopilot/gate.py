"""agentcouncil.autopilot.gate -- real gate execution through protocol backends.

Replaces stub gate logic in the orchestrator with real protocol sessions
(review_loop, challenge, brainstorm, review, decide) routed through the
AgentCouncil backend infrastructure.

Gate execution creates a session with the configured outside backend,
runs the appropriate protocol, and returns a normalized GateDecision.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from agentcouncil.adapters import resolve_lead_adapter, resolve_lead_settings
from agentcouncil.autopilot.artifacts import GateDecision
from agentcouncil.autopilot.normalizer import GateNormalizer

logger = logging.getLogger(__name__)

__all__ = ["GateExecutor"]


class GateExecutor:
    """Executes real protocol gates through AgentCouncil backends.

    Wraps the async protocol functions (review_loop, challenge, etc.) in
    synchronous calls suitable for the LinearOrchestrator's gate loop.

    Usage:
        executor = GateExecutor(backend="codex")
        decision, raw = executor.run_gate("review_loop", artifact_text="...")
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        challenge_backend: Optional[str] = None,
        lead_backend: Optional[str] = None,
        lead_model: Optional[str] = None,
        normalizer: Optional[GateNormalizer] = None,
    ) -> None:
        """Initialize the gate executor.

        Args:
            backend: Named backend profile for the outside agent. When omitted,
                _make_provider resolves the configured default profile, legacy
                env var, then built-in default.
            challenge_backend: Optional backend profile for challenge gates.
                Defaults to backend when omitted.
            lead_backend: Optional lead backend/profile. Defaults to the lead
                resolver's configured default.
            lead_model: Optional lead model override.
            normalizer: GateNormalizer instance. Defaults to GateNormalizer().
        """
        self._backend = backend
        self._challenge_backend = challenge_backend or self._backend
        self._lead_backend = lead_backend
        self._lead_model = lead_model
        self._normalizer = normalizer or GateNormalizer()

    def run_gate(
        self,
        gate_type: str,
        artifact_text: str = "",
        stage_name: str = "",
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run a protocol gate and return (GateDecision, raw_artifact).

        Dispatches to the appropriate protocol based on gate_type:
        - review_loop: iterative review convergence
        - challenge: adversarial stress-testing
        - review: single review pass
        - brainstorm: deliberation for consensus
        - decide: option evaluation

        Args:
            gate_type: Protocol type to run.
            artifact_text: Text content to review/challenge/deliberate on.
            stage_name: Name of the stage being gated (for context).
            **kwargs: Additional protocol-specific arguments.

        Returns:
            Tuple of (normalized GateDecision, raw protocol artifact).
        """
        handler = {
            "review_loop": self._run_review_loop,
            "challenge": self._run_challenge,
            "review": self._run_review,
            "brainstorm": self._run_brainstorm,
            "decide": self._run_decide,
        }.get(gate_type)

        if handler is None:
            logger.warning("Unknown gate_type %r, falling back to advance", gate_type)
            return GateDecision(
                decision="advance",
                protocol_type="review_loop",
                protocol_session_id="unknown-gate-type",
                rationale=f"Unknown gate_type={gate_type!r}; auto-advancing.",
            ), None

        return handler(artifact_text, stage_name, **kwargs)

    # ------------------------------------------------------------------
    # Protocol runners
    # ------------------------------------------------------------------

    def _create_session(self, backend: Optional[str] = None) -> tuple[Any, Any, Any, Any, Any]:
        """Create outside session + adapter and lead adapter.

        Returns (provider, session, outside_adapter, lead_adapter, transcript_meta).
        """
        from agentcouncil.config import BackendProfile, ProfileLoader
        from agentcouncil.runtime import OutsideRuntime
        from agentcouncil.schemas import TranscriptMeta
        from agentcouncil.session import OutsideSession, OutsideSessionAdapter
        from agentcouncil.server import _make_provider

        from agentcouncil.server import _get_workspace_sync
        selected_backend = self._backend if backend is None else backend
        workspace = _get_workspace_sync()
        provider = _make_provider(profile=selected_backend, workspace=workspace)
        resolved = ProfileLoader().resolve(profile_name=selected_backend)
        provider_name = resolved.provider if isinstance(resolved, BackendProfile) else str(resolved)
        outside_model = (
            resolved.model if isinstance(resolved, BackendProfile) else None
        ) or getattr(provider, "_model", None)
        runtime = OutsideRuntime(provider, workspace=workspace)
        session = OutsideSession(
            provider,
            runtime,
            profile=selected_backend,
            model=outside_model,
            provider_name=provider_name,
        )
        outside = OutsideSessionAdapter(session)
        lead_provider, resolved_lead_model = resolve_lead_settings(
            backend=self._lead_backend,
            model=self._lead_model,
            default_claude_model="opus",
        )
        lead = resolve_lead_adapter(
            backend=self._lead_backend,
            timeout=900,
            model=self._lead_model,
            default_claude_model="opus",
        )
        meta = TranscriptMeta(
            lead_backend=lead_provider,
            lead_model=resolved_lead_model,
            outside_backend=provider_name,
            outside_model=session.model,
            outside_transport="session",
            independence_tier=(
                "same_backend_fresh_session"
                if provider_name == lead_provider
                else "cross_backend"
            ),
            outside_provider=session.provider_name,
            outside_profile=session.profile,
            outside_session_mode=session.session_mode,
            outside_workspace_access=session.workspace_access,
        )

        return provider, session, outside, lead, meta

    def _run_in_loop(self, coro: Any, timeout: float = 900) -> Any:
        """Run an async coroutine synchronously with timeout.

        Args:
            coro: Async coroutine to execute.
            timeout: Maximum seconds to wait (default 900s / 15 minutes).

        Raises:
            TimeoutError: If the protocol doesn't complete within timeout.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(coro, timeout=timeout)
            )
        finally:
            loop.close()

    def _check_certification(self, protocol: str, profile: Optional[str], model_id: Optional[str]) -> None:
        """Apply the same review/challenge certification gate as direct MCP tools."""
        from agentcouncil.certifier import CertificationCache, check_certification_gate

        check_certification_gate(
            protocol,
            model_id=model_id,
            profile=profile,
            cache=CertificationCache(),
        )

    def _run_review_loop(
        self,
        artifact_text: str,
        stage_name: str,
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run review_loop protocol and normalize the result."""
        from agentcouncil.convergence import review_loop

        prior_review_context = kwargs.get("prior_review_context")

        provider, session, outside, lead, meta = self._create_session(self._backend)
        self._check_certification("review", session.profile, meta.outside_model)

        async def _execute() -> Any:
            await session.open()
            try:
                result = await review_loop(
                    artifact=artifact_text,
                    artifact_type="code",
                    outside_adapter=outside,
                    lead_adapter=lead,
                    review_objective=f"Gate review for stage '{stage_name}'",
                    max_iterations=3,
                    prior_review_context=prior_review_context,
                    outside_meta=meta,
                )
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        session_id = getattr(provider, "_session_id", None) or "review-loop-gate"

        decision = self._normalizer.normalize("review_loop", result, session_id)
        return decision, result

    def _run_challenge(
        self,
        artifact_text: str,
        stage_name: str,
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run challenge protocol and normalize the result."""
        from agentcouncil.challenge import challenge
        from agentcouncil.schemas import ChallengeInput

        provider, session, outside, lead, meta = self._create_session(self._challenge_backend)
        self._check_certification("challenge", session.profile, meta.outside_model)

        challenge_input = ChallengeInput(
            artifact=artifact_text,
            assumptions=[],
            success_criteria=f"Stage '{stage_name}' output is production-ready",
            rounds=2,
        )

        async def _execute() -> Any:
            await session.open()
            try:
                result = await challenge(challenge_input, outside, lead, outside_meta=meta)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        # challenge returns DeliberationResult[ChallengeArtifact]
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(provider, "_session_id", None) or "challenge-gate"

        decision = self._normalizer.normalize("challenge", raw_artifact, session_id)
        return decision, raw_artifact

    def _run_review(
        self,
        artifact_text: str,
        stage_name: str,
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run single review protocol and normalize the result."""
        from agentcouncil.review import review
        from agentcouncil.schemas import ReviewInput

        provider, session, outside, lead, meta = self._create_session(self._backend)
        self._check_certification("review", session.profile, meta.outside_model)

        review_input = ReviewInput(
            artifact=artifact_text,
            review_objective=f"Gate review for stage '{stage_name}'",
        )

        async def _execute() -> Any:
            await session.open()
            try:
                result = await review(review_input, outside, lead, outside_meta=meta)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(provider, "_session_id", None) or "review-gate"

        decision = self._normalizer.normalize("review", raw_artifact, session_id)
        return decision, raw_artifact

    def _run_brainstorm(
        self,
        artifact_text: str,
        stage_name: str,
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run brainstorm protocol and normalize the result."""
        from agentcouncil.deliberation import brainstorm
        from agentcouncil.brief import Brief

        provider, session, outside, lead, meta = self._create_session(self._backend)

        brief = Brief(
            problem_statement=artifact_text,
            background=f"Gate brainstorm for stage '{stage_name}'.",
            constraints=[],
            goals=[f"Decide whether stage '{stage_name}' output should advance."],
            open_questions=[],
        )

        async def _execute() -> Any:
            await session.open()
            try:
                result = await brainstorm(brief, outside, lead, outside_meta=meta)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        # brainstorm returns BrainstormResult with .artifact (ConsensusArtifact)
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(provider, "_session_id", None) or "brainstorm-gate"

        decision = self._normalizer.normalize("brainstorm", raw_artifact, session_id)
        return decision, raw_artifact

    def _run_decide(
        self,
        artifact_text: str,
        stage_name: str,
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run decide protocol and normalize the result."""
        from agentcouncil.decide import decide
        from agentcouncil.schemas import DecideInput, DecideOption

        provider, session, outside, lead, meta = self._create_session(self._backend)

        decide_input = DecideInput(
            decision=f"Should stage '{stage_name}' output advance to the next stage?",
            options=[
                DecideOption(id="advance", label="Advance", description="Advance to next stage"),
                DecideOption(id="revise", label="Revise", description="Send back for revision"),
                DecideOption(id="block", label="Block", description="Block and escalate"),
            ],
            criteria=artifact_text,
        )

        async def _execute() -> Any:
            await session.open()
            try:
                result = await decide(decide_input, outside, lead, outside_meta=meta)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(provider, "_session_id", None) or "decide-gate"

        decision = self._normalizer.normalize("decide", raw_artifact, session_id)
        return decision, raw_artifact
