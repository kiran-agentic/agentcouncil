from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcouncil.schemas import DecideInput, DecideOption


def _make_options():
    return [
        DecideOption(id="advance", label="Advance", description="Advance to next stage"),
        DecideOption(id="revise", label="Revise", description="Send back for revision"),
        DecideOption(id="block", label="Block", description="Block and escalate"),
    ]


def test_decide_input_old_fields_raises():
    """The old gate.py usage (context=, question=) must raise ValidationError."""
    with pytest.raises(ValidationError):
        DecideInput(
            context="some artifact",
            question="Should stage advance?",
            options=_make_options(),
        )


def test_decide_input_fixed_fields_valid():
    """The corrected usage (decision=, criteria=) must construct without error."""
    di = DecideInput(
        decision="Should stage 'build' output advance to the next stage?",
        options=_make_options(),
        criteria="some artifact text",
    )
    assert di.decision == "Should stage 'build' output advance to the next stage?"
    assert len(di.options) == 3
    assert di.criteria == "some artifact text"
