"""Review deliberation function (REV-07 through REV-11).

Implements evaluative-only review using the dual-independent protocol
from run_deliberation(). Findings describe impact, not fixes.
"""

from __future__ import annotations

from typing import Optional

from agentcouncil.adapters import AgentAdapter
from agentcouncil.deliberation import OnEvent, run_deliberation
from agentcouncil.schemas import (
    ConsensusStatus,
    DeliberationResult,
    ReviewArtifact,
    ReviewInput,
    TranscriptMeta,
)

__all__ = ["review"]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

REVIEW_INPUT_PROMPT = """\
You are reviewing an artifact. Analyze it independently and produce your findings.

## Artifact ({artifact_type})

{artifact}

{objective_section}
{focus_section}
{prior_context_section}

Produce an independent review. For each finding, state:
- What the issue is
- Its severity (critical/high/medium/low)
- Its impact on the system
- Evidence from the artifact
- Your confidence level (high/medium/low)

Be evaluative only: describe impact, do NOT suggest fixes or implementation changes."""

REVIEW_INPUT_PROMPT_PATHS = """\
You are reviewing an artifact. Read the files listed below, then analyze independently and produce your findings.

## Artifact ({artifact_type})

Read these files:
{file_list}

{objective_section}
{focus_section}
{prior_context_section}

Produce an independent review. For each finding, state:
- What the issue is
- Its severity (critical/high/medium/low)
- Its impact on the system
- Evidence from the artifact (reference file paths and line numbers)
- Your confidence level (high/medium/low)

Be evaluative only: describe impact, do NOT suggest fixes or implementation changes."""


def _build_input_prompt(ri: ReviewInput, workspace_access: str = "none") -> str:
    """Build the factual input prompt from ReviewInput (REV-10: no opinion).

    When workspace_access is "native" and file_paths are provided, builds a
    path-reference prompt instead of embedding artifact content.
    """
    objective_section = ""
    if ri.review_objective:
        objective_section = f"## Review Objective\n{ri.review_objective}"

    focus_section = ""
    if ri.focus_areas:
        items = "\n".join(f"- {area}" for area in ri.focus_areas)
        focus_section = f"## Focus Areas\n{items}"

    prior_context_section = ""
    if ri.prior_review_context:
        prior_context_section = (
            "## Prior Review Context\n"
            "This artifact is a revision. The prior review produced the findings below. "
            "Verify each one: is it resolved by this revision, still present, or newly regressed? "
            "Also flag any NEW issues introduced by the revision itself.\n\n"
            f"{ri.prior_review_context}"
        )

    if workspace_access == "native" and ri.file_paths:
        file_list = "\n".join(f"- {p}" for p in ri.file_paths)
        return REVIEW_INPUT_PROMPT_PATHS.format(
            artifact_type=ri.artifact_type,
            file_list=file_list,
            objective_section=objective_section,
            focus_section=focus_section,
            prior_context_section=prior_context_section,
        )

    return REVIEW_INPUT_PROMPT.format(
        artifact_type=ri.artifact_type,
        artifact=ri.artifact,
        objective_section=objective_section,
        focus_section=focus_section,
        prior_context_section=prior_context_section,
    )


# ---------------------------------------------------------------------------
# Synthesis prompt function
# ---------------------------------------------------------------------------


def _review_synthesis_prompt_fn(
    input_prompt: str,
    outside_initial: str,
    lead_initial: str,
    discussion: str,
    schema_json: str,
) -> str:
    """Build the synthesis prompt for review (REV-07, REV-08, REV-09).

    Instructs the synthesizer to:
    - State impact, NOT fixes or implementation recommendations (REV-07)
    - Acknowledge that the lead may have confirmed, disputed, or added findings (REV-08)
    - PRESERVE disputed findings -- do NOT collapse them into consensus (REV-09)
    """
    return f"""\
You have seen two independent reviews of the same artifact, followed by discussion.

## Original Review Prompt
{input_prompt}

## Outside Agent's Review
{outside_initial}

## Lead Agent's Review
{lead_initial}

## Discussion
{discussion}

## Instructions

Synthesize the reviews into a single structured output. Follow these rules strictly:

1. Each finding must state impact, NOT fixes or implementation recommendations. \
Do NOT include implementation recommendations or suggested code changes.
2. The lead agent may have confirmed, disputed, or added findings the outside agent \
missed. Reflect this accurately.
3. PRESERVE disputed findings in the output -- do NOT collapse them into consensus. \
If agents disagree on a finding, set agreement to "disputed".
4. Set finding.agreement to "confirmed" if both agents agree, "disputed" if they disagree.
5. Set finding.origin to "outside" if only outside raised it, "lead" if only lead raised it, \
"both" if both independently identified it.
6. Include priority (P1/P2/P3) ONLY if the original artifact_type is code.
7. Verdict guidance: "pass" if no critical or high findings, "revise" if any high or above, \
"escalate" if critical findings with high confidence.

Return your response as JSON matching this schema:
{schema_json}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def review(
    review_input: ReviewInput,
    outside_adapter: AgentAdapter,
    lead_adapter: AgentAdapter,
    on_event: Optional[OnEvent] = None,
    outside_meta: Optional[TranscriptMeta] = None,
    checkpoint_callback: Optional[OnEvent] = None,
    workspace_access: str = "none",
) -> DeliberationResult:
    """Run the review deliberation protocol.

    Args:
        review_input: ReviewInput with artifact, artifact_type, optional objective/focus/rounds.
        outside_adapter: AgentAdapter for the independent outside reviewer.
        lead_adapter: AgentAdapter for the lead reviewer.
        on_event: Optional event callback for progress tracking.
        workspace_access: Backend workspace capability ("native", "assisted", "none").
            When "native" and file_paths are set, prompts reference paths instead of
            embedding content.

    Returns:
        DeliberationResult[ReviewArtifact] with verdict, findings, strengths,
        open_questions, next_action.

    Raises:
        ValueError: If review_input.artifact is empty and no file_paths provided.
    """
    # Validate input before any adapter calls
    has_content = review_input.artifact and review_input.artifact.strip()
    has_paths = bool(review_input.file_paths)
    if not has_content and not has_paths:
        raise ValueError("artifact must not be empty (or provide file_paths)")

    # Build factual input prompt (REV-10: no opinion)
    input_prompt = _build_input_prompt(review_input, workspace_access=workspace_access)

    # Run dual-independent deliberation with ReviewArtifact
    return await run_deliberation(
        input_prompt=input_prompt,
        outside_adapter=outside_adapter,
        lead_adapter=lead_adapter,
        artifact_cls=ReviewArtifact,
        synthesis_prompt_fn=_review_synthesis_prompt_fn,
        exchange_rounds=review_input.rounds,
        on_event=on_event,
        derive_status=_review_derive_status,
        outside_meta=outside_meta,
        checkpoint_callback=checkpoint_callback,
    )


def _review_derive_status(artifact: ReviewArtifact) -> ConsensusStatus:
    """Derive envelope status from review findings (COM-03)."""
    if any(f.agreement == "disputed" for f in artifact.findings):
        return ConsensusStatus.consensus_with_reservations
    return ConsensusStatus.consensus
