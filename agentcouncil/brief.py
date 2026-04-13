from __future__ import annotations

import json
import re
from typing import List, Optional

from pydantic import BaseModel, ValidationError

from agentcouncil.adapters import AgentAdapter

__all__ = [
    "Brief",
    "CodeExcerpt",
    "BriefBuilder",
    "ContaminatedBriefError",
    "BriefExtractionError",
    "CONTAMINATION_PATTERNS",
]


# ---------------------------------------------------------------------------
# Contamination patterns — deterministic first-person Claude-voice scanner
# Scoped to first-person singular/directive voice only.
# Third-party attribution ("the team decided", "engineers recommend") does NOT match.
# Historical references ("previous design proposed") do NOT match.
# Code context is excluded from contamination scanning (caller-supplied verbatim).
# ---------------------------------------------------------------------------

CONTAMINATION_PATTERNS = [
    r"\bI (recommend|suggest|propose|would use|would implement|prefer)\b",
    r"\bmy (recommendation|suggestion|proposal|preferred|approach)\b",
    # "we should" only when NOT preceded by third-party attribution verbs (reported speech)
    r"(?<!decided )(?<!determined )(?<!agreed )(?<!think that )(?<!said )\bwe should (use|adopt|implement|go with)\b",
    r"\bthe best (approach|solution|option|choice) is\b",
    r"\byou should (use|adopt|implement)\b",
    r"\bI think (we|you) should\b",
    r"\bmy (preferred|proposed) (solution|approach|design|direction)\b",
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


_CODE_FENCE_RE = re.compile(
    r"^```(?:json|JSON)?\s*\n(.*?)\n```\s*$",
    re.DOTALL,
)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if the text is wrapped in them.

    LLMs (including Claude) sometimes wrap JSON responses in ```json ... ```
    blocks even when instructed to return plain JSON. This strips those fences
    before JSON parsing so callers always receive raw JSON.

    Only strips a single outer fence — nested fences within the content are
    left unchanged. If no fence is present, the text is returned unchanged.
    """
    match = _CODE_FENCE_RE.match(text.strip())
    if match:
        return match.group(1)
    return text


# ---------------------------------------------------------------------------
# Extraction prompt template
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a technical brief writer. Extract ONLY facts, context, constraints, goals, and open questions from the following input. Do NOT include any proposed solution, recommendation, preferred approach, or implied direction. Do NOT state what you think should be done.

Output as JSON with these exact keys:
- problem_statement: string
- background: string
- constraints: list of strings
- goals: list of strings
- open_questions: list of strings

Input:
{raw_context}"""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CodeExcerpt(BaseModel):
    """A verbatim code or file excerpt included in the brief for code-aware context."""

    path: str
    content: str


class Brief(BaseModel):
    """Structured problem brief passed to the outside agent.

    The brief contains only factual context — no proposed solution, preferred approach,
    or Claude opinion language. This is enforced by BriefBuilder._check_contamination()
    before the brief is returned.
    """

    problem_statement: str
    background: str
    constraints: List[str]
    goals: List[str]
    open_questions: List[str]
    code_context: Optional[List[CodeExcerpt]] = None

    def to_prompt(self) -> str:
        """Render the brief as a readable markdown string for Phase 4 consumption.

        This is the canonical rendering of a Brief — Phase 4 calls this method
        rather than implementing its own serialization. Format is locked here to
        prevent cross-phase mismatch.
        """
        lines: list[str] = []

        lines.append("# Problem Brief")
        lines.append("")
        lines.append("## Problem Statement")
        lines.append("")
        lines.append(self.problem_statement)
        lines.append("")

        if self.background:
            lines.append("## Background")
            lines.append("")
            lines.append(self.background)
            lines.append("")

        if self.constraints:
            lines.append("## Constraints")
            lines.append("")
            for constraint in self.constraints:
                lines.append(f"- {constraint}")
            lines.append("")

        if self.goals:
            lines.append("## Goals")
            lines.append("")
            for goal in self.goals:
                lines.append(f"- {goal}")
            lines.append("")

        if self.open_questions:
            lines.append("## Open Questions")
            lines.append("")
            for question in self.open_questions:
                lines.append(f"- {question}")
            lines.append("")

        if self.code_context:
            lines.append("## Code Context")
            lines.append("")
            for excerpt in self.code_context:
                lines.append(f"### `{excerpt.path}`")
                lines.append("")
                lines.append("```")
                lines.append(excerpt.content)
                lines.append("```")
                lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ContaminatedBriefError(ValueError):
    """Raised when a brief contains Claude's proposed solution or implied direction.

    This is the existential correctness guarantee of AgentCouncil. When raised,
    the brief must never be passed to the outside agent — contaminated briefs
    defeat the independence-before-convergence protocol.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"Brief contamination detected: {reason}")
        self.reason = reason


class BriefExtractionError(ValueError):
    """Raised when the LLM response cannot be parsed into a valid Brief.

    Distinguishes extraction failures (malformed JSON, wrong schema) from
    contamination violations (ContaminatedBriefError) and adapter failures
    (AdapterError).
    """

    pass


# ---------------------------------------------------------------------------
# BriefBuilder
# ---------------------------------------------------------------------------


class BriefBuilder:
    """Extracts a contamination-safe Brief from raw context via an LLM adapter.

    Usage:
        builder = BriefBuilder(adapter=StubAdapter(valid_json))
        brief = builder.build("raw context string")

    The adapter is injected to support deterministic testing. In production,
    ClaudeAdapter is used by default (imported lazily to avoid PATH check at
    module load time).
    """

    def __init__(self, adapter: AgentAdapter | None = None) -> None:
        if adapter is None:
            # Import lazily to avoid EnvironmentError at module load if claude not on PATH
            from agentcouncil.adapters import ClaudeAdapter

            adapter = ClaudeAdapter()
        self._adapter = adapter

    def build(
        self,
        raw_context: str,
        code_context: list[CodeExcerpt] | None = None,
    ) -> Brief:
        """Extract a Brief from raw_context, check contamination, return Brief or raise.

        Args:
            raw_context: Free-form text describing the problem, context, and constraints.
            code_context: Optional list of verbatim file excerpts. These are included
                verbatim and are NOT scanned for contamination (caller-supplied content).

        Returns:
            Brief: A validated, contamination-free brief ready for the outside agent.

        Raises:
            BriefExtractionError: If the LLM response cannot be parsed into a Brief.
            ContaminatedBriefError: If any extracted text field contains Claude opinion language.
            AdapterError: If the underlying adapter call fails (propagates unchanged).
        """
        brief = self._extract(raw_context, code_context)
        self._check_contamination(brief)
        return brief

    def _extract(
        self,
        raw_context: str,
        code_context: list[CodeExcerpt] | None = None,
    ) -> Brief:
        """Call the adapter to extract structured fields from raw_context.

        Args:
            raw_context: Free-form problem description.
            code_context: Optional verbatim code excerpts to attach after extraction.

        Returns:
            Brief: Parsed from the LLM response (code_context attached if provided).

        Raises:
            BriefExtractionError: If JSON parsing or Pydantic validation fails.
            AdapterError: If the adapter call fails (propagates unchanged).
        """
        prompt = EXTRACTION_PROMPT.format(raw_context=raw_context)
        response = self._adapter.call(prompt)

        # Strip markdown code fences if the LLM wraps JSON in ```json ... ``` blocks.
        # Claude CLI sometimes adds these even when instructed to return plain JSON.
        response = _strip_code_fences(response)

        try:
            brief = Brief.model_validate_json(response)
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            raise BriefExtractionError(
                f"Failed to parse LLM response into Brief: {exc}"
            ) from exc

        if code_context is not None:
            brief = brief.model_copy(update={"code_context": code_context})

        return brief

    def _check_contamination(self, brief: Brief) -> None:
        """Scan all extracted text fields for Claude opinion language.

        Checks: problem_statement, background, all constraints, all goals,
        all open_questions. Does NOT check code_context — that is caller-supplied
        verbatim content (see research pitfall 1).

        Raises:
            ContaminatedBriefError: If any contamination pattern is matched.
        """
        text_fields = [
            brief.problem_statement,
            brief.background,
            *brief.constraints,
            *brief.goals,
            *brief.open_questions,
        ]
        combined = " ".join(text_fields)

        for pattern in CONTAMINATION_PATTERNS:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                raise ContaminatedBriefError(
                    f"pattern '{pattern}' matched '{match.group()}'"
                )
