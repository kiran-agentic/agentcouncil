from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, TypeVar

from pydantic import BaseModel, Field, ValidationError

from agentcouncil.adapters import AgentAdapter, AdapterError
from agentcouncil.brief import Brief
from agentcouncil.schemas import (
    ConsensusArtifact,
    ConsensusStatus,
    DeliberationResult,
    Transcript,
    TranscriptMeta,
    TranscriptTurn,
    TurnPhase,
)

T = TypeVar("T", bound=BaseModel)

__all__ = ["Exchange", "RoundTranscript", "BrainstormResult", "brainstorm", "run_deliberation", "DeriveStatus"]

log = logging.getLogger("agentcouncil.deliberation")

_CODE_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output before JSON parsing."""
    match = _CODE_FENCE_RE.match(text.strip())
    if match:
        return match.group(1)
    return text


class Exchange(BaseModel):
    """A single exchange in the negotiation phase.

    Deprecated: Use TranscriptTurn with phase="exchange" instead (TN-04).
    """

    role: str  # "outside" or "lead"
    content: str


class RoundTranscript(BaseModel):
    """Full provenance of a brainstorm run - one field per round.

    Deprecated: brainstorm() now returns Transcript instead (TN-04).
    Kept for backward compatibility with code that imports this class.
    """

    brief_prompt: str
    outside_proposal: Optional[str] = None
    lead_proposal: Optional[str] = None
    exchanges: List[Exchange] = Field(default_factory=list)
    negotiation_output: Optional[str] = None
    meta: Optional[TranscriptMeta] = None


class BrainstormResult(BaseModel):
    """Return type of brainstorm(). Always populated, even on partial failure."""

    artifact: ConsensusArtifact
    transcript: Transcript


# ---------------------------------------------------------------------------
# Prompt templates (module-level constants)
# ---------------------------------------------------------------------------

LEAD_PROMPT_TEMPLATE = """\
You are the lead agent in a brainstorm session. An outside agent has independently
proposed a solution to the problem below. Review their proposal, then develop your
own proposal. You may agree, disagree, or propose a different approach.

## Brief
{brief_prompt}

## Outside Agent Proposal
{outside_proposal}

Provide your own proposal for solving this problem."""

OUTSIDE_EXCHANGE_TEMPLATE = """\
You are the outside agent in a brainstorm negotiation. You and a lead agent have
each proposed solutions to the problem below. Review the lead agent's latest
response and continue the discussion. Push back where you disagree, acknowledge
where they make good points, and refine your position.

## Brief
{brief_prompt}

## Your Original Proposal
{outside_proposal}

## Lead Agent's Original Proposal
{lead_proposal}

## Discussion So Far
{discussion}

Respond in free text. Be specific about what you agree with, what you reject,
and what you'd change. Do NOT produce JSON yet — that comes in the final round."""

LEAD_EXCHANGE_TEMPLATE = """\
You are the lead agent in a brainstorm negotiation. You and an outside agent have
each proposed solutions to the problem below. Review the outside agent's latest
response and continue the discussion. Push back where you disagree, acknowledge
where they make good points, and refine your position.

## Brief
{brief_prompt}

## Outside Agent's Original Proposal
{outside_proposal}

## Your Original Proposal
{lead_proposal}

## Discussion So Far
{discussion}

Respond in free text. Be specific about what you agree with, what you reject,
and what you'd change. Do NOT produce JSON yet — that comes in the final round."""

NEGOTIATION_PROMPT_TEMPLATE = """\
You have seen two independent proposals for the following problem brief,
followed by a multi-round discussion between the agents.

## Brief
{brief_prompt}

## Proposal A (Outside Agent)
{outside_proposal}

## Proposal B (Lead Agent)
{lead_proposal}

## Discussion
{discussion}

Based on the full discussion, produce a final synthesis. Identify points of
agreement, points of disagreement, and propose a recommended direction.
Return your response as JSON with these exact keys:
{schema}"""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _partial_failure_result(
    brief_prompt: str,
    error: str,
    stage: str,
    outside_proposal: Optional[str] = None,
    lead_proposal: Optional[str] = None,
    exchanges: Optional[List[TranscriptTurn]] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> BrainstormResult:
    """Build a BrainstormResult with partial_failure status.

    Transcript is populated through the last successful round only.
    Never raises — always returns a valid BrainstormResult.
    """
    artifact = ConsensusArtifact(
        recommended_direction=f"{stage} agent failed — {error}",
        agreement_points=[],
        disagreement_points=[],
        rejected_alternatives=[],
        open_risks=[f"{stage} agent error: {error}"],
        next_action="Retry or inspect adapter configuration",
        status=ConsensusStatus.partial_failure,
    )
    transcript = Transcript(
        input_prompt=brief_prompt,
        outside_initial=outside_proposal,
        lead_initial=lead_proposal,
        exchanges=exchanges or [],
        final_output=None,
        meta=outside_meta,
    )
    return BrainstormResult(artifact=artifact, transcript=transcript)


def _unresolved_disagreement_result(
    brief_prompt: str,
    outside_proposal: str,
    lead_proposal: str,
    negotiation_output: str,
    exchanges: Optional[List[TranscriptTurn]] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> BrainstormResult:
    """Build a BrainstormResult with unresolved_disagreement status.

    Used when the negotiation round produces output that cannot be parsed as JSON.
    The raw negotiation_output is preserved in the transcript.
    """
    artifact = ConsensusArtifact(
        recommended_direction="Negotiation failed to produce structured consensus",
        agreement_points=[],
        disagreement_points=[],
        rejected_alternatives=[],
        open_risks=["Negotiation output was not valid JSON"],
        next_action="Review transcript and retry or accept disagreement",
        status=ConsensusStatus.unresolved_disagreement,
    )
    transcript = Transcript(
        input_prompt=brief_prompt,
        outside_initial=outside_proposal,
        lead_initial=lead_proposal,
        exchanges=exchanges or [],
        final_output=negotiation_output,
        meta=outside_meta,
    )
    return BrainstormResult(artifact=artifact, transcript=transcript)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _format_discussion(exchanges: List[TranscriptTurn]) -> str:
    """Format exchange history into a readable discussion block."""
    if not exchanges:
        return "(No prior discussion — this is the first exchange.)"
    parts = []
    for i, ex in enumerate(exchanges, 1):
        label = "Outside Agent" if ex.role == "outside" else "Lead Agent"
        parts.append(f"### Round {i} ({label})\n{ex.content}")
    return "\n\n".join(parts)


def _filtered_schema() -> str:
    """Return ConsensusArtifact JSON schema with partial_failure filtered out."""
    raw_schema = ConsensusArtifact.model_json_schema()
    for loc in (
        raw_schema.get("properties", {}).get("status", {}),
        raw_schema.get("$defs", {}).get("ConsensusStatus", {}),
    ):
        if "enum" in loc:
            loc["enum"] = [s for s in loc["enum"] if s != "partial_failure"]
    return json.dumps(raw_schema, indent=2)


# Event callback type: fn(event_name: str, data: dict) -> None
OnEvent = Callable[[str, Dict[str, Any]], None]


def _noop_event(event: str, data: Dict[str, Any]) -> None:
    pass


async def brainstorm(
    brief: Brief,
    outside_adapter: AgentAdapter,
    lead_adapter: AgentAdapter,
    negotiation_rounds: int = 1,
    on_event: Optional[OnEvent] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> BrainstormResult:
    """Run the deliberation protocol and return a structured result.

    Round 1: Outside agent sees only the brief (context isolation).
    Round 2: Lead agent sees brief + outside proposal.
    Rounds 3..N: Free-text exchanges — agents alternate responding to each other.
        Outside goes first, then lead, alternating for `negotiation_rounds` pairs.
        When negotiation_rounds=1 (default), this phase is skipped and the protocol
        behaves identically to the original 4-round version.
    Final: Outside agent synthesizes the full discussion into structured JSON.

    On AdapterError at any round: returns partial_failure with transcript
    populated through the last successful round. Never re-raises AdapterError.

    On JSON parse failure at synthesis: returns unresolved_disagreement
    with full transcript including the raw non-JSON output.

    Never retries on failure. Never raises to the caller.
    """
    emit = on_event or _noop_event
    t0 = time.time()
    brief_prompt = brief.to_prompt()
    log.debug("brainstorm started — brief_prompt=%d chars, negotiation_rounds=%d",
             len(brief_prompt), negotiation_rounds)
    emit("start", {"negotiation_rounds": negotiation_rounds})

    # Round 1 — Outside proposal (outside sees ONLY brief)
    emit("step", {"agent": "codex", "step": "propose", "status": "active"})
    log.debug("[round 1] calling outside adapter (codex)...")
    t1 = time.time()
    try:
        outside_proposal = await outside_adapter.acall(brief_prompt)
    except AdapterError as e:
        log.warning("[round 1] outside adapter failed after %.1fs: %s", time.time() - t1, e)
        emit("step", {"agent": "codex", "step": "propose", "status": "error", "error": str(e)})
        return _partial_failure_result(
            brief_prompt=brief_prompt,
            error=str(e),
            stage="outside",
            outside_meta=outside_meta,
        )
    log.debug("[round 1] outside adapter done — %.1fs, response=%d chars",
             time.time() - t1, len(outside_proposal))
    emit("step", {"agent": "codex", "step": "propose", "status": "done", "elapsed": time.time() - t1})

    # Round 2 — Lead proposal (lead sees brief + outside proposal)
    lead_prompt = LEAD_PROMPT_TEMPLATE.format(
        brief_prompt=brief_prompt,
        outside_proposal=outside_proposal,
    )
    emit("step", {"agent": "claude", "step": "propose", "status": "active"})
    emit("arrow", {"direction": "codex_to_claude", "label": "proposal"})
    log.debug("[round 2] calling lead adapter (claude)...")
    t2 = time.time()
    try:
        lead_proposal = await lead_adapter.acall(lead_prompt)
    except AdapterError as e:
        log.warning("[round 2] lead adapter failed after %.1fs: %s", time.time() - t2, e)
        emit("step", {"agent": "claude", "step": "propose", "status": "error", "error": str(e)})
        return _partial_failure_result(
            brief_prompt=brief_prompt,
            error=str(e),
            stage="lead",
            outside_proposal=outside_proposal,
            outside_meta=outside_meta,
        )
    log.debug("[round 2] lead adapter done — %.1fs, response=%d chars",
             time.time() - t2, len(lead_proposal))
    emit("step", {"agent": "claude", "step": "propose", "status": "done", "elapsed": time.time() - t2})

    # Exchange rounds — agents alternate free-text responses.
    # negotiation_rounds=1 means no exchanges (original behavior).
    # negotiation_rounds=2 means 1 pair of exchanges before synthesis, etc.
    exchanges: List[TranscriptTurn] = []

    for round_num in range(negotiation_rounds - 1):
        discussion = _format_discussion(exchanges)

        # Outside responds
        outside_exchange_prompt = OUTSIDE_EXCHANGE_TEMPLATE.format(
            brief_prompt=brief_prompt,
            outside_proposal=outside_proposal,
            lead_proposal=lead_proposal,
            discussion=discussion,
        )
        emit("step", {"agent": "codex", "step": f"exchange {round_num + 1}", "status": "active"})
        emit("arrow", {"direction": "claude_to_codex", "label": f"exchange {round_num + 1}"})
        log.debug("[exchange %d] calling outside adapter...", round_num + 1)
        te = time.time()
        try:
            outside_response = await outside_adapter.acall(outside_exchange_prompt)
        except AdapterError as e:
            log.warning("[exchange %d] outside failed after %.1fs: %s",
                      round_num + 1, time.time() - te, e)
            emit("step", {"agent": "codex", "step": f"exchange {round_num + 1}", "status": "error"})
            return _partial_failure_result(
                brief_prompt=brief_prompt,
                error=str(e),
                stage=f"exchange-{round_num + 1}-outside",
                outside_proposal=outside_proposal,
                lead_proposal=lead_proposal,
                exchanges=exchanges,
                outside_meta=outside_meta,
            )
        log.debug("[exchange %d] outside done — %.1fs", round_num + 1, time.time() - te)
        emit("step", {"agent": "codex", "step": f"exchange {round_num + 1}", "status": "done", "elapsed": time.time() - te})
        exchanges.append(TranscriptTurn(role="outside", content=outside_response, phase="exchange"))

        # Lead responds
        discussion = _format_discussion(exchanges)
        lead_exchange_prompt = LEAD_EXCHANGE_TEMPLATE.format(
            brief_prompt=brief_prompt,
            outside_proposal=outside_proposal,
            lead_proposal=lead_proposal,
            discussion=discussion,
        )
        emit("step", {"agent": "claude", "step": f"exchange {round_num + 1}", "status": "active"})
        emit("arrow", {"direction": "codex_to_claude", "label": f"exchange {round_num + 1}"})
        log.debug("[exchange %d] calling lead adapter...", round_num + 1)
        te2 = time.time()
        try:
            lead_response = await lead_adapter.acall(lead_exchange_prompt)
        except AdapterError as e:
            log.warning("[exchange %d] lead failed after %.1fs: %s",
                      round_num + 1, time.time() - te2, e)
            emit("step", {"agent": "claude", "step": f"exchange {round_num + 1}", "status": "error"})
            return _partial_failure_result(
                brief_prompt=brief_prompt,
                error=str(e),
                stage=f"exchange-{round_num + 1}-lead",
                outside_proposal=outside_proposal,
                lead_proposal=lead_proposal,
                exchanges=exchanges,
                outside_meta=outside_meta,
            )
        log.debug("[exchange %d] lead done — %.1fs", round_num + 1, time.time() - te2)
        emit("step", {"agent": "claude", "step": f"exchange {round_num + 1}", "status": "done", "elapsed": time.time() - te2})
        exchanges.append(TranscriptTurn(role="lead", content=lead_response, phase="exchange"))

    # Final round — Outside synthesizes into structured JSON.
    discussion = _format_discussion(exchanges)
    schema = _filtered_schema()
    negotiation_prompt = NEGOTIATION_PROMPT_TEMPLATE.format(
        brief_prompt=brief_prompt,
        outside_proposal=outside_proposal,
        lead_proposal=lead_proposal,
        discussion=discussion,
        schema=schema,
    )
    emit("step", {"agent": "codex", "step": "synthesize", "status": "active"})
    emit("arrow", {"direction": "both", "label": "synthesis"})
    log.debug("[synthesis] calling outside adapter for JSON synthesis...")
    ts = time.time()
    try:
        negotiation_output = await outside_adapter.acall(negotiation_prompt)
    except AdapterError as e:
        log.warning("[synthesis] outside failed after %.1fs: %s", time.time() - ts, e)
        emit("step", {"agent": "codex", "step": "synthesize", "status": "error"})
        return _partial_failure_result(
            brief_prompt=brief_prompt,
            error=str(e),
            stage="negotiation",
            outside_proposal=outside_proposal,
            lead_proposal=lead_proposal,
            exchanges=exchanges,
            outside_meta=outside_meta,
        )
    log.debug("[synthesis] outside done — %.1fs", time.time() - ts)
    emit("step", {"agent": "codex", "step": "synthesize", "status": "done", "elapsed": time.time() - ts})

    # Parse negotiation output as ConsensusArtifact.
    # Strip markdown code fences before parsing — codex/claude may wrap JSON in ```...```.
    negotiation_json = _strip_code_fences(negotiation_output)
    try:
        artifact = ConsensusArtifact.model_validate_json(negotiation_json)
    except (ValidationError, json.JSONDecodeError, ValueError):
        return _unresolved_disagreement_result(
            brief_prompt=brief_prompt,
            outside_proposal=outside_proposal,
            lead_proposal=lead_proposal,
            negotiation_output=negotiation_output,
            exchanges=exchanges,
            outside_meta=outside_meta,
        )

    # Guard: partial_failure is system-assigned only, never a valid negotiation outcome.
    if artifact.status == ConsensusStatus.partial_failure:
        return _unresolved_disagreement_result(
            brief_prompt=brief_prompt,
            outside_proposal=outside_proposal,
            lead_proposal=lead_proposal,
            negotiation_output=negotiation_output,
            exchanges=exchanges,
            outside_meta=outside_meta,
        )

    log.debug("brainstorm complete — status=%s, total=%.1fs",
             artifact.status, time.time() - t0)
    emit("done", {"status": artifact.status, "elapsed": time.time() - t0})

    transcript = Transcript(
        input_prompt=brief_prompt,
        outside_initial=outside_proposal,
        lead_initial=lead_proposal,
        exchanges=exchanges,
        final_output=negotiation_output,
        meta=outside_meta,
    )
    return BrainstormResult(artifact=artifact, transcript=transcript)


# ---------------------------------------------------------------------------
# Dual-Independent Protocol Runner
# ---------------------------------------------------------------------------

DUAL_OUTSIDE_EXCHANGE = """\
You are the outside agent. You and a lead agent independently analyzed the same \
problem. Review the lead agent's analysis and the discussion so far. Push back \
where you disagree, acknowledge good points.

## Original Problem
{input_prompt}

## Your Initial Analysis
{outside_initial}

## Lead Agent's Initial Analysis
{lead_initial}

## Discussion So Far
{discussion}

Respond in free text. Do NOT produce JSON."""

DUAL_LEAD_EXCHANGE = """\
You are the lead agent. You and an outside agent independently analyzed the same \
problem. Review the outside agent's analysis and the discussion so far. Push back \
where you disagree, acknowledge good points.

## Original Problem
{input_prompt}

## Outside Agent's Initial Analysis
{outside_initial}

## Your Initial Analysis
{lead_initial}

## Discussion So Far
{discussion}

Respond in free text. Do NOT produce JSON."""


def _generic_filtered_schema(artifact_cls: type[BaseModel]) -> str:
    """Return artifact JSON schema with partial_failure filtered out of any enum."""
    raw_schema = artifact_cls.model_json_schema()
    # Walk through properties and $defs to remove partial_failure from enums
    for loc in (
        raw_schema.get("properties", {}).get("status", {}),
        raw_schema.get("$defs", {}).get("ConsensusStatus", {}),
    ):
        if "enum" in loc:
            loc["enum"] = [s for s in loc["enum"] if s != "partial_failure"]
    return json.dumps(raw_schema, indent=2)


def _build_minimal_artifact(
    artifact_cls: type[T],
    error_msg: str,
) -> T:
    """Build a minimal valid artifact for failure envelopes (COM-12 round-trip safe).

    Tries enum value permutations until a valid artifact is constructed.
    Falls back to model_construct only as last resort.
    """
    schema = artifact_cls.model_json_schema()
    props = schema.get("properties", {})

    # Collect base kwargs and track enum fields for permutation
    base_kwargs: Dict[str, Any] = {}
    enum_fields: Dict[str, list] = {}
    optional_str_fields: list[str] = []
    for name, prop in props.items():
        if "enum" in prop and prop["enum"]:
            enum_fields[name] = prop["enum"]
            base_kwargs[name] = prop["enum"][0]
        elif prop.get("type") == "string":
            base_kwargs[name] = error_msg
        elif prop.get("type") == "array":
            base_kwargs[name] = []
        elif "anyOf" in prop:
            # Check if any variant is string type — populate with error_msg
            # so validators requiring non-empty optional strings pass (e.g. defer_reason)
            has_string = any(
                v.get("type") == "string" for v in prop["anyOf"] if isinstance(v, dict)
            )
            base_kwargs[name] = error_msg if has_string else None
            if has_string:
                optional_str_fields.append(name)

    # Try base kwargs first
    try:
        return artifact_cls(**base_kwargs)
    except (ValidationError, ValueError):
        pass

    # Try alternative enum values for each enum field
    for field_name, values in enum_fields.items():
        for val in values[1:]:
            base_kwargs[field_name] = val
            try:
                return artifact_cls(**base_kwargs)
            except (ValidationError, ValueError):
                continue
        # Reset to first value before trying next field
        base_kwargs[field_name] = values[0]

    # Last resort: model_construct (breaks COM-12 but avoids crash)
    return artifact_cls.model_construct(**base_kwargs)


def _generic_partial_failure(
    artifact_cls: type[T],
    input_prompt: str,
    error: str,
    stage: str,
    outside_initial: Optional[str] = None,
    lead_initial: Optional[str] = None,
    exchanges: Optional[List[TranscriptTurn]] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> DeliberationResult:
    """Build a partial_failure DeliberationResult with transcript through last success."""
    artifact = _build_minimal_artifact(artifact_cls, f"{stage} failed — {error}")

    transcript = Transcript(
        input_prompt=input_prompt,
        outside_initial=outside_initial,
        lead_initial=lead_initial,
        exchanges=exchanges or [],
        final_output=None,
        meta=outside_meta,
    )
    return DeliberationResult(
        deliberation_status=ConsensusStatus.partial_failure,
        artifact=artifact,
        transcript=transcript,
    )


def _generic_unresolved(
    artifact_cls: type[T],
    input_prompt: str,
    outside_initial: str,
    lead_initial: str,
    raw_output: str,
    exchanges: Optional[List[TranscriptTurn]] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> DeliberationResult:
    """Build an unresolved_disagreement result with raw output preserved."""
    artifact = _build_minimal_artifact(
        artifact_cls, "Negotiation failed to produce structured consensus",
    )

    transcript = Transcript(
        input_prompt=input_prompt,
        outside_initial=outside_initial,
        lead_initial=lead_initial,
        exchanges=exchanges or [],
        final_output=raw_output,
        meta=outside_meta,
    )
    return DeliberationResult(
        deliberation_status=ConsensusStatus.unresolved_disagreement,
        artifact=artifact,
        transcript=transcript,
    )


def _format_exchange_discussion(exchanges: List[TranscriptTurn]) -> str:
    """Format TranscriptTurn exchange history into a readable discussion block."""
    if not exchanges:
        return "(No prior discussion — this is the first exchange.)"
    parts = []
    for i, turn in enumerate(exchanges, 1):
        label = "Outside Agent" if turn.role == "outside" else "Lead Agent"
        parts.append(f"### Round {i} ({label})\n{turn.content}")
    return "\n\n".join(parts)


DeriveStatus = Callable[[Any], ConsensusStatus]


async def run_deliberation(
    input_prompt: str,
    outside_adapter: AgentAdapter,
    lead_adapter: AgentAdapter,
    artifact_cls: type[T],
    synthesis_prompt_fn: Callable[[str, str, str, str, str], str],
    exchange_rounds: int = 1,
    on_event: Optional[OnEvent] = None,
    lead_input_prompt: Optional[str] = None,
    derive_status: Optional[DeriveStatus] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> DeliberationResult:
    """Run the dual-independent deliberation protocol and return a structured result.

    Both agents receive the same factual input independently -- neither sees the
    other's initial analysis (COM-06). This differs from brainstorm's outside-first
    pattern where the lead sees the outside proposal.

    Parameters:
        input_prompt: Factual input sent to the outside agent.
        outside_adapter: AgentAdapter for the outside agent.
        lead_adapter: AgentAdapter for the lead agent.
        artifact_cls: Pydantic model class for the function-specific artifact.
        synthesis_prompt_fn: Callable(input_prompt, outside_initial, lead_initial,
            discussion, schema_json) -> synthesis prompt string.
        exchange_rounds: Number of exchange pairs before synthesis. Default 1 = no exchanges.
        on_event: Optional event callback.
        lead_input_prompt: Optional separate prompt for the lead agent (CHL-08).
            When provided, the lead sees this instead of input_prompt for the
            independent phase. Both prompts must contain the same factual context
            but may differ in framing (e.g. attack vs defense). When None, both
            agents receive input_prompt.
        derive_status: Optional callback to derive deliberation_status from the
            parsed artifact. When None, defaults to ConsensusStatus.consensus.
        outside_meta: Optional TranscriptMeta to attach to the result transcript.
            When provided, result.transcript.meta is set to this value. When None,
            transcript.meta remains None (backward-compatible default).

    Returns:
        DeliberationResult -- always populated, never raises AdapterError.
    """
    emit = on_event or _noop_event
    t0 = time.time()

    # COM-11: Input validation -- abort before any adapter call
    if not input_prompt or not input_prompt.strip():
        raise ValueError("input_prompt must not be empty")

    log.debug("run_deliberation started — input=%d chars, exchange_rounds=%d",
              len(input_prompt), exchange_rounds)
    emit("start", {"exchange_rounds": exchange_rounds})

    # Phase 1: Independent initial analysis (COM-06)
    # Outside agent sees only input_prompt
    emit("step", {"agent": "outside", "step": "initial", "status": "active"})
    try:
        outside_initial = await outside_adapter.acall(input_prompt)
    except AdapterError as e:
        log.warning("outside initial failed: %s", e)
        emit("step", {"agent": "outside", "step": "initial", "status": "error"})
        return _generic_partial_failure(
            artifact_cls, input_prompt, str(e), "outside",
            outside_meta=outside_meta,
        )
    emit("step", {"agent": "outside", "step": "initial", "status": "done"})

    # Lead agent sees lead_input_prompt (or input_prompt if not provided) -- NOT outside_initial (COM-06)
    lead_prompt = lead_input_prompt if lead_input_prompt is not None else input_prompt
    emit("step", {"agent": "lead", "step": "initial", "status": "active"})
    try:
        lead_initial = await lead_adapter.acall(lead_prompt)
    except AdapterError as e:
        log.warning("lead initial failed: %s", e)
        emit("step", {"agent": "lead", "step": "initial", "status": "error"})
        return _generic_partial_failure(
            artifact_cls, input_prompt, str(e), "lead",
            outside_initial=outside_initial,
            outside_meta=outside_meta,
        )
    emit("step", {"agent": "lead", "step": "initial", "status": "done"})

    # Phase 2: Exchange rounds
    exchanges: List[TranscriptTurn] = []

    for round_num in range(exchange_rounds - 1):
        discussion = _format_exchange_discussion(exchanges)

        # Outside exchange
        outside_exchange_prompt = DUAL_OUTSIDE_EXCHANGE.format(
            input_prompt=input_prompt,
            outside_initial=outside_initial,
            lead_initial=lead_initial,
            discussion=discussion,
        )
        emit("step", {"agent": "outside", "step": f"exchange {round_num + 1}", "status": "active"})
        try:
            outside_response = await outside_adapter.acall(outside_exchange_prompt)
        except AdapterError as e:
            log.warning("outside exchange %d failed: %s", round_num + 1, e)
            emit("step", {"agent": "outside", "step": f"exchange {round_num + 1}", "status": "error"})
            return _generic_partial_failure(
                artifact_cls, input_prompt, str(e),
                f"exchange-{round_num + 1}-outside",
                outside_initial=outside_initial,
                lead_initial=lead_initial,
                exchanges=exchanges,
                outside_meta=outside_meta,
            )
        exchanges.append(TranscriptTurn(role="outside", content=outside_response))
        emit("step", {"agent": "outside", "step": f"exchange {round_num + 1}", "status": "done"})

        # Lead exchange
        discussion = _format_exchange_discussion(exchanges)
        lead_exchange_prompt = DUAL_LEAD_EXCHANGE.format(
            input_prompt=input_prompt,
            outside_initial=outside_initial,
            lead_initial=lead_initial,
            discussion=discussion,
        )
        emit("step", {"agent": "lead", "step": f"exchange {round_num + 1}", "status": "active"})
        try:
            lead_response = await lead_adapter.acall(lead_exchange_prompt)
        except AdapterError as e:
            log.warning("lead exchange %d failed: %s", round_num + 1, e)
            emit("step", {"agent": "lead", "step": f"exchange {round_num + 1}", "status": "error"})
            return _generic_partial_failure(
                artifact_cls, input_prompt, str(e),
                f"exchange-{round_num + 1}-lead",
                outside_initial=outside_initial,
                lead_initial=lead_initial,
                exchanges=exchanges,
                outside_meta=outside_meta,
            )
        exchanges.append(TranscriptTurn(role="lead", content=lead_response))
        emit("step", {"agent": "lead", "step": f"exchange {round_num + 1}", "status": "done"})

    # Phase 3: Synthesis
    discussion = _format_exchange_discussion(exchanges)
    schema_json = _generic_filtered_schema(artifact_cls)
    synthesis_prompt = synthesis_prompt_fn(
        input_prompt, outside_initial, lead_initial, discussion, schema_json,
    )

    emit("step", {"agent": "outside", "step": "synthesize", "status": "active"})
    try:
        synthesis_output = await outside_adapter.acall(synthesis_prompt)
    except AdapterError as e:
        log.warning("synthesis failed: %s", e)
        emit("step", {"agent": "outside", "step": "synthesize", "status": "error"})
        return _generic_partial_failure(
            artifact_cls, input_prompt, str(e), "synthesis",
            outside_initial=outside_initial,
            lead_initial=lead_initial,
            exchanges=exchanges,
            outside_meta=outside_meta,
        )
    emit("step", {"agent": "outside", "step": "synthesize", "status": "done"})

    # Parse synthesis output
    synthesis_json = _strip_code_fences(synthesis_output)
    try:
        artifact = artifact_cls.model_validate_json(synthesis_json)
    except (ValidationError, json.JSONDecodeError, ValueError):
        return _generic_unresolved(
            artifact_cls, input_prompt, outside_initial, lead_initial,
            synthesis_output, exchanges,
            outside_meta=outside_meta,
        )

    # Guard: partial_failure is system-assigned only (COM-10)
    for field_name in ("status", "deliberation_status"):
        val = getattr(artifact, field_name, None)
        if val == "partial_failure" or val == ConsensusStatus.partial_failure:
            return _generic_unresolved(
                artifact_cls, input_prompt, outside_initial, lead_initial,
                synthesis_output, exchanges,
                outside_meta=outside_meta,
            )

    # Derive envelope status from parsed artifact (COM-03)
    if derive_status is not None:
        status = derive_status(artifact)
    else:
        status = ConsensusStatus.consensus

    elapsed = time.time() - t0
    log.debug("run_deliberation complete — status=%s, %.1fs", status, elapsed)
    emit("done", {"status": status, "elapsed": elapsed})

    transcript = Transcript(
        input_prompt=input_prompt,
        outside_initial=outside_initial,
        lead_initial=lead_initial,
        exchanges=exchanges,
        final_output=synthesis_output,
        meta=outside_meta,
    )
    return DeliberationResult(
        deliberation_status=status,
        artifact=artifact,
        transcript=transcript,
    )
