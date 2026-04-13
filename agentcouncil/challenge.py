"""Challenge deliberation function (CHL-08, CHL-09, CHL-11, CHL-12).

Implements adversarial stress-testing using the dual-independent protocol
from run_deliberation(). Challenge attacks assumptions and finds failure
modes -- it does NOT propose repairs or fixes.
"""

from __future__ import annotations

from typing import Optional

from agentcouncil.adapters import AgentAdapter
from agentcouncil.deliberation import OnEvent, run_deliberation
from agentcouncil.schemas import (
    ChallengeArtifact,
    ChallengeInput,
    ConsensusStatus,
    DeliberationResult,
    TranscriptMeta,
)

__all__ = ["challenge"]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

CHALLENGE_ATTACK_PROMPT = """\
You are stress-testing a plan or design. Your goal is to find failure modes, \
attack assumptions, and identify conditions under which this plan breaks.

## Target Artifact

{artifact}

{assumptions_section}
{success_criteria_section}
{constraints_section}

Identify failure modes and attack assumptions. For each failure mode, state:
- Which assumption it attacks
- Description of the failure
- Severity (critical/high/medium/low)
- Impact on the system
- Your confidence level (high/medium/low)

Be adversarial: find ways this plan fails. Do NOT propose repairs or fixes."""

CHALLENGE_DEFENSE_PROMPT = """\
You are defending a plan or design against adversarial stress-testing. Your goal \
is to identify the plan's strengths, explain why key assumptions hold, and \
anticipate where an attacker might probe — then argue why those attacks would fail.

## Target Artifact

{artifact}

{assumptions_section}
{success_criteria_section}
{constraints_section}

For each assumption or design choice, explain:
- Why it holds under realistic conditions
- What evidence or reasoning supports it
- Under what conditions it could break (be honest about limits)

Be a rigorous defender: argue from evidence, not optimism. Acknowledge genuine \
weaknesses but explain why they are acceptable or mitigated."""


def _build_sections(ci: ChallengeInput) -> dict[str, str]:
    """Build shared factual sections from ChallengeInput (CHL-12: no opinion, no defense strategy)."""
    assumptions_section = ""
    if ci.assumptions:
        items = "\n".join(f"{i+1}. {a}" for i, a in enumerate(ci.assumptions))
        assumptions_section = f"## Assumptions\n{items}"

    success_criteria_section = ""
    if ci.success_criteria:
        success_criteria_section = f"## Success Criteria\n{ci.success_criteria}"

    constraints_section = ""
    if ci.constraints:
        constraints_section = f"## Constraints\n{ci.constraints}"

    return {
        "artifact": ci.artifact,
        "assumptions_section": assumptions_section,
        "success_criteria_section": success_criteria_section,
        "constraints_section": constraints_section,
    }


def _build_attack_prompt(ci: ChallengeInput) -> str:
    """Build the attack prompt for the outside agent."""
    return CHALLENGE_ATTACK_PROMPT.format(**_build_sections(ci))


def _build_defense_prompt(ci: ChallengeInput) -> str:
    """Build the defense prompt for the lead agent (CHL-08)."""
    return CHALLENGE_DEFENSE_PROMPT.format(**_build_sections(ci))


# ---------------------------------------------------------------------------
# Synthesis prompt function
# ---------------------------------------------------------------------------


def _challenge_synthesis_prompt_fn(
    input_prompt: str,
    outside_initial: str,
    lead_initial: str,
    discussion: str,
    schema_json: str,
) -> str:
    """Build the synthesis prompt for challenge (CHL-09, CHL-11).

    Instructs the synthesizer to:
    - Attack assumptions, do NOT propose repairs or fixes (CHL-11)
    - Reference defense arguments for exchange context (CHL-09)
    - Set readiness=ready ONLY if no credible attack found (CHL-10)
    - Set disposition accurately for each failure mode
    """
    return f"""\
You have seen two independent analyses of the same plan/design, followed by discussion.

## Original Challenge Prompt
{input_prompt}

## Outside Agent's Attack
{outside_initial}

## Lead Agent's Defense
{lead_initial}

## Discussion (attack on defense arguments)
{discussion}

## Instructions

Synthesize the adversarial challenge into a single structured output. Follow these rules strictly:

1. This is adversarial only: attack assumptions, do NOT propose repairs or fixes. \
Do NOT suggest mitigations or improvements.
2. Exchange rounds attack the lead's defense arguments, not the original artifact. \
Evaluate whether the defense arguments hold up under scrutiny.
3. Set readiness to "ready" ONLY if no credible attack was found (failure_modes may be empty). \
Set readiness to "needs_hardening" if attacks found but plan is salvageable. \
Set readiness to "not_ready" if fundamental flaws found.
4. For each failure_mode, set disposition accurately:
   - "must_harden" if the attack succeeded and the assumption needs strengthening
   - "monitor" if the attack is plausible but not yet proven
   - "mitigated" if existing measures address the attack
   - "accepted_risk" if the risk is real but acceptable
   - "invalidated" if the attack was refuted by the defense
5. Include surviving_assumptions (assumptions that withstood attack), \
break_conditions (conditions under which the plan fails), \
and residual_risks (risks that remain after challenge).

Return your response as JSON matching this schema:
{schema_json}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def challenge(
    challenge_input: ChallengeInput,
    outside_adapter: AgentAdapter,
    lead_adapter: AgentAdapter,
    on_event: Optional[OnEvent] = None,
    outside_meta: Optional[TranscriptMeta] = None,
) -> DeliberationResult:
    """Run the challenge deliberation protocol.

    Args:
        challenge_input: ChallengeInput with artifact, optional assumptions/success_criteria/
            constraints/rounds.
        outside_adapter: AgentAdapter for the independent outside attacker.
        lead_adapter: AgentAdapter for the lead defender.
        on_event: Optional event callback for progress tracking.

    Returns:
        DeliberationResult[ChallengeArtifact] with readiness, failure_modes,
        surviving_assumptions, break_conditions, residual_risks, next_action.

    Raises:
        ValueError: If challenge_input.artifact is empty.
    """
    # Validate input before any adapter calls
    if not challenge_input.artifact or not challenge_input.artifact.strip():
        raise ValueError("artifact must not be empty")

    # Build separate attack/defense prompts (CHL-08: independent attack + defense)
    attack_prompt = _build_attack_prompt(challenge_input)
    defense_prompt = _build_defense_prompt(challenge_input)

    # Run dual-independent deliberation with ChallengeArtifact
    return await run_deliberation(
        input_prompt=attack_prompt,
        outside_adapter=outside_adapter,
        lead_adapter=lead_adapter,
        artifact_cls=ChallengeArtifact,
        synthesis_prompt_fn=_challenge_synthesis_prompt_fn,
        exchange_rounds=challenge_input.rounds,
        on_event=on_event,
        lead_input_prompt=defense_prompt,
        derive_status=_challenge_derive_status,
        outside_meta=outside_meta,
    )


def _challenge_derive_status(artifact: ChallengeArtifact) -> ConsensusStatus:
    """Derive envelope status from challenge readiness (COM-03)."""
    if artifact.readiness == "ready":
        return ConsensusStatus.consensus
    return ConsensusStatus.consensus_with_reservations
