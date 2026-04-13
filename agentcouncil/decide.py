"""Decide deliberation function (DEC-09 through DEC-12).

Implements option-constrained decision evaluation using the dual-independent
protocol from run_deliberation(). Agents evaluate only caller-provided options
with assumptions, tradeoffs, and confidence for every option.
"""

from __future__ import annotations

from typing import Optional

import logging

from agentcouncil.adapters import AgentAdapter
from agentcouncil.deliberation import OnEvent, run_deliberation
from agentcouncil.schemas import (
    ConsensusStatus,
    DecideArtifact,
    DecideInput,
    DeliberationResult,
    Transcript,
    TranscriptMeta,
)

log = logging.getLogger("agentcouncil.decide")

__all__ = ["decide"]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

DECIDE_INPUT_PROMPT = """\
You are evaluating a decision. Analyze the options independently.

## Decision Question

{decision}

## Options

{options_section}

{criteria_section}
{constraints_section}

Evaluate ONLY the options listed above. Do NOT propose new options.

For each option, assess:
- Pros and cons
- Blocking risks
- Your confidence level (high/medium/low)

Provide an independent, factual analysis. Do NOT express a preference or ranking."""


def _build_input_prompt(di: DecideInput) -> str:
    """Build the factual input prompt from DecideInput (DEC-11: no preference)."""
    options_lines = []
    for opt in di.options:
        options_lines.append(f"### {opt.id}: {opt.label}\n{opt.description}")
    options_section = "\n\n".join(options_lines)

    criteria_section = ""
    if di.criteria:
        criteria_section = f"## Criteria\n{di.criteria}"

    constraints_section = ""
    if di.constraints:
        constraints_section = f"## Constraints\n{di.constraints}"

    return DECIDE_INPUT_PROMPT.format(
        decision=di.decision,
        options_section=options_section,
        criteria_section=criteria_section,
        constraints_section=constraints_section,
    )


# ---------------------------------------------------------------------------
# Synthesis prompt function
# ---------------------------------------------------------------------------


def _decide_synthesis_prompt_fn(
    input_prompt: str,
    outside_initial: str,
    lead_initial: str,
    discussion: str,
    schema_json: str,
) -> str:
    """Build the synthesis prompt for decide (DEC-09, DEC-10).

    Instructs the synthesizer to:
    - Evaluate ONLY the caller-provided options, do NOT invent new options (DEC-09)
    - Include assumptions, tradeoffs, and confidence for EVERY option even when
      one is the clear winner (DEC-10)
    - Set disposition accurately (selected/viable/rejected/insufficient_information)
    """
    return f"""\
You have seen two independent decision analyses, followed by discussion.

## Original Decision Prompt
{input_prompt}

## Outside Agent's Analysis
{outside_initial}

## Lead Agent's Analysis
{lead_initial}

## Discussion
{discussion}

## Instructions

Synthesize the analyses into a single structured decision output. Follow these rules strictly:

1. Evaluate ONLY the provided options. Do NOT invent new options or propose alternatives \
not in the original list.
2. For EVERY option, include assumptions, tradeoffs, and confidence -- even when one \
option is the clear winner. Do NOT skip assessments for losing options.
3. Set disposition accurately for each option:
   - "selected" if this is the winning option
   - "viable" if reasonable but not chosen
   - "rejected" if clearly inferior or has blocking risks
   - "insufficient_information" if cannot be properly evaluated
4. Outcome guidance:
   - "decided" if one option is clearly superior
   - "deferred" if insufficient information to decide (provide defer_reason)
   - "experiment" if options need real-world validation (provide experiment_plan)
5. If outcome is "decided", set winner_option_id to the selected option's id.
6. Include blocking_risks for any option with serious concerns.

Return your response as JSON matching this schema:
{schema_json}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def decide(
    decide_input: DecideInput,
    outside_adapter: AgentAdapter,
    lead_adapter: AgentAdapter,
    on_event: Optional[OnEvent] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> DeliberationResult:
    """Run the decide deliberation protocol.

    Args:
        decide_input: DecideInput with decision, options, optional criteria/constraints/rounds.
        outside_adapter: AgentAdapter for the independent outside evaluator.
        lead_adapter: AgentAdapter for the lead evaluator.
        on_event: Optional event callback for progress tracking.

    Returns:
        DeliberationResult[DecideArtifact] with outcome, option_assessments,
        decision_summary, next_action.

    Raises:
        ValueError: If decide_input.decision is empty.
    """
    # Validate input before any adapter calls
    if not decide_input.decision or not decide_input.decision.strip():
        raise ValueError("decision must not be empty")

    # Build factual input prompt (DEC-11: no preference)
    input_prompt = _build_input_prompt(decide_input)

    # Run dual-independent deliberation with DecideArtifact
    result = await run_deliberation(
        input_prompt=input_prompt,
        outside_adapter=outside_adapter,
        lead_adapter=lead_adapter,
        artifact_cls=DecideArtifact,
        synthesis_prompt_fn=_decide_synthesis_prompt_fn,
        exchange_rounds=decide_input.rounds,
        on_event=on_event,
        derive_status=_decide_derive_status,
        outside_meta=outside_meta,
    )

    # Post-parse option validation (DEC-09): verify option IDs match input
    if result.deliberation_status not in (
        ConsensusStatus.partial_failure,
        ConsensusStatus.unresolved_disagreement,
    ):
        valid_ids = {opt.id for opt in decide_input.options}
        artifact = result.artifact

        if artifact.winner_option_id and artifact.winner_option_id not in valid_ids:
            log.warning("winner_option_id '%s' not in input options %s",
                       artifact.winner_option_id, valid_ids)
            return DeliberationResult(
                deliberation_status=ConsensusStatus.unresolved_disagreement,
                artifact=artifact,
                transcript=result.transcript,
            )

        invalid_assessments = [
            a.option_id for a in artifact.option_assessments
            if a.option_id not in valid_ids
        ]
        if invalid_assessments:
            log.warning("option_assessments contain invalid IDs: %s", invalid_assessments)
            return DeliberationResult(
                deliberation_status=ConsensusStatus.unresolved_disagreement,
                artifact=artifact,
                transcript=result.transcript,
            )

    return result


def _decide_derive_status(artifact: DecideArtifact) -> ConsensusStatus:
    """Derive envelope status from decision outcome (COM-03)."""
    if artifact.outcome in ("deferred", "experiment"):
        return ConsensusStatus.consensus_with_reservations
    return ConsensusStatus.consensus
