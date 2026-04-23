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
from typing import Any, Callable, Optional

from agentcouncil.autopilot.artifacts import GateDecision
from agentcouncil.autopilot.normalizer import GateNormalizer

logger = logging.getLogger(__name__)

__all__ = ["GateExecutor"]


def _get_event_loop() -> asyncio.AbstractEventLoop:
    """Get or create an event loop for running async protocol code."""
    try:
        loop = asyncio.get_running_loop()
        # If we're already in an async context, we can't use asyncio.run
        # This shouldn't happen in the autopilot pipeline (synchronous)
        return loop
    except RuntimeError:
        pass
    return asyncio.new_event_loop()


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
        normalizer: Optional[GateNormalizer] = None,
    ) -> None:
        """Initialize the gate executor.

        Args:
            backend: Named backend profile for the outside agent.
                Defaults to AGENTCOUNCIL_OUTSIDE_AGENT env var, then None
                (which lets _make_provider pick the default).
            normalizer: GateNormalizer instance. Defaults to GateNormalizer().
        """
        import os
        self._backend = backend or os.environ.get("AGENTCOUNCIL_OUTSIDE_AGENT")
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

    def _create_session(self) -> tuple[Any, Any, Any, Any]:
        """Create outside session + adapter and lead adapter.

        Returns (provider, session, outside_adapter, lead_adapter).
        """
        from agentcouncil.adapters import ClaudeAdapter
        from agentcouncil.runtime import OutsideRuntime
        from agentcouncil.session import OutsideSession, OutsideSessionAdapter
        from agentcouncil.server import _make_provider

        from agentcouncil.server import _get_workspace_sync
        provider = _make_provider(profile=self._backend)
        runtime = OutsideRuntime(provider, workspace=_get_workspace_sync())
        session = OutsideSession(provider, runtime, profile=self._backend)
        outside = OutsideSessionAdapter(session)
        lead = ClaudeAdapter(model="opus", timeout=900)

        return provider, session, outside, lead

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

    def _run_review_loop(
        self,
        artifact_text: str,
        stage_name: str,
        **kwargs: Any,
    ) -> tuple[GateDecision, Any]:
        """Run review_loop protocol and normalize the result."""
        from agentcouncil.convergence import review_loop

        prior_review_context = kwargs.get("prior_review_context")

        provider, session, outside, lead = self._create_session()

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
                )
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        session_id = getattr(result, "session_id", "review-loop-gate")

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

        provider, session, outside, lead = self._create_session()

        challenge_input = ChallengeInput(
            artifact=artifact_text,
            assumptions=[],
            success_criteria=f"Stage '{stage_name}' output is production-ready",
            rounds=2,
        )

        async def _execute() -> Any:
            await session.open()
            try:
                result = await challenge(challenge_input, outside, lead)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        # challenge returns DeliberationResult[ChallengeArtifact]
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(result, "session_id", "challenge-gate")

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

        provider, session, outside, lead = self._create_session()

        review_input = ReviewInput(
            artifact=artifact_text,
            review_objective=f"Gate review for stage '{stage_name}'",
        )

        async def _execute() -> Any:
            await session.open()
            try:
                result = await review(review_input, outside, lead)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(result, "session_id", "review-gate")

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
        from agentcouncil.brief import Brief, BriefBuilder

        provider, session, outside, lead = self._create_session()

        brief = BriefBuilder(
            context=artifact_text,
            question=f"Should stage '{stage_name}' output advance to the next stage?",
        ).build()

        async def _execute() -> Any:
            await session.open()
            try:
                result = await brainstorm(brief, outside, lead)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        # brainstorm returns BrainstormResult with .artifact (ConsensusArtifact)
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(result, "session_id", "brainstorm-gate")

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

        provider, session, outside, lead = self._create_session()

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
                result = await decide(decide_input, outside, lead)
                return result
            finally:
                await provider.close()
                await session.close()

        result = self._run_in_loop(_execute())
        raw_artifact = result.artifact if hasattr(result, "artifact") else result
        session_id = getattr(result, "session_id", "decide-gate")

        decision = self._normalizer.normalize("decide", raw_artifact, session_id)
        return decision, raw_artifact


def make_gate_runner(
    gate_executor: GateExecutor,
    gate_type: str,
    artifact_fn: Callable[[], str],
    stage_name: str = "",
) -> Callable[[], GateDecision]:
    """Create a gate runner callable compatible with LinearOrchestrator.gate_runners.

    The returned callable captures the gate_executor and produces a GateDecision
    when called (no arguments).

    Args:
        gate_executor: GateExecutor instance.
        gate_type: Protocol type (review_loop, challenge, etc.).
        artifact_fn: Callable that returns the text to gate on (called lazily).
        stage_name: Stage being gated (for context).

    Returns:
        A no-arg callable returning GateDecision.
    """
    def runner() -> GateDecision:
        artifact_text = artifact_fn()
        decision, _ = gate_executor.run_gate(
            gate_type, artifact_text=artifact_text, stage_name=stage_name,
        )
        return decision

    return runner
