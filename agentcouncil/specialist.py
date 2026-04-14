"""agentcouncil.specialist — Expert Witness: Protocol-Scoped Specialist Checks (EW-01..EW-13).

Provides bounded specialist consultation where a specialist agent receives
only a targeted sub-question and minimal context slice, returns typed
evaluative output, and the result is inserted as provenance-tagged evidence.

The module is generic over protocol-owned Pydantic artifact types.
Protocol-specific schemas (ChallengeSpecialistAssessment, ReviewSpecialistFinding,
DecideSpecialistEvaluation) are defined in schemas.py.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from agentcouncil.schemas import TranscriptTurn

__all__ = ["specialist_check", "make_specialist_turn"]

log = logging.getLogger("agentcouncil.specialist")

T = TypeVar("T", bound=BaseModel)

_CODE_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _CODE_FENCE_RE.match(text.strip())
    return m.group(1) if m else text


def _build_specialist_prompt(
    sub_question: str,
    context_slice: str,
    artifact_cls: type[T],
) -> str:
    """Build a bounded prompt for the specialist (EW-02)."""
    schema_json = json.dumps(artifact_cls.model_json_schema(), indent=2)
    return f"""\
You are a specialist providing an independent assessment on a specific question.
Answer ONLY the question below using the provided context. Be evaluative, not prescriptive.

## Question
{sub_question}

## Context
{context_slice}

## Response Format
Return your assessment as JSON matching this schema:
{schema_json}"""


async def specialist_check(
    sub_question: str,
    context_slice: str,
    specialist_adapter: Any,
    artifact_cls: type[T],
) -> Optional[T]:
    """Run a bounded specialist check (EW-01).

    Sends only the sub_question and context_slice to the specialist (EW-02).
    Returns a typed artifact or None on failure (EW-13).

    Args:
        sub_question: The specific question to evaluate.
        context_slice: Minimal context — NOT the full debate transcript.
        specialist_adapter: AgentAdapter for the specialist.
        artifact_cls: Pydantic model class for the expected output.

    Returns:
        Parsed artifact of type T, or None if the specialist fails.
    """
    prompt = _build_specialist_prompt(sub_question, context_slice, artifact_cls)

    try:
        response = await specialist_adapter.acall(prompt)
    except Exception as e:
        # EW-13: Failure is graceful — protocol continues
        log.warning("specialist check failed (adapter error): %s", e)
        return None

    # Parse response
    cleaned = _strip_fences(response)
    try:
        artifact = artifact_cls.model_validate_json(cleaned)
        return artifact
    except (ValidationError, json.JSONDecodeError, ValueError) as e:
        log.warning("specialist check failed (parse error): %s", e)
        return None


def make_specialist_turn(
    artifact: BaseModel,
    sub_question: str,
    parent_turn_id: Optional[str] = None,
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
) -> TranscriptTurn:
    """Create a TranscriptTurn for specialist evidence (EW-08, EW-09).

    Args:
        artifact: The parsed specialist artifact.
        sub_question: The question that was asked.
        parent_turn_id: ID of the exchange turn that triggered the check (EW-09).
        provider_name: Specialist provider name for provenance.
        model_name: Specialist model name for provenance.

    Returns:
        TranscriptTurn with phase="specialist" and full provenance.
    """
    content = (
        f"## Specialist Assessment\n\n"
        f"**Question:** {sub_question}\n\n"
        f"**Assessment:**\n```json\n{artifact.model_dump_json(indent=2)}\n```"
    )
    return TranscriptTurn(
        role="specialist",
        content=content,
        phase="specialist",
        parent_turn_id=parent_turn_id,
        actor_provider=provider_name,
        actor_model=model_name,
        timestamp=time.time(),
    )
