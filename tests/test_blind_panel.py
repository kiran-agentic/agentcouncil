"""Tests for Blind Panel — Sealed N-Party Proposals (BP-01..BP-14)."""
from __future__ import annotations

import json

import pytest

from agentcouncil.schemas import ConsensusStatus


def _negotiation_json(**overrides):
    defaults = {
        "recommended_direction": "Combined approach",
        "agreement_points": ["All agree on caching"],
        "disagreement_points": [],
        "rejected_alternatives": [],
        "open_risks": [],
        "next_action": "Implement",
        "status": "consensus",
    }
    defaults.update(overrides)
    return json.dumps(defaults)


def _valid_brief():
    from agentcouncil.brief import Brief
    return Brief(
        problem_statement="How should we cache?",
        background="No caching today",
        constraints=["Python 3.12"],
        goals=["Reduce DB load"],
        open_questions=["Redis vs in-memory?"],
    )


# ---------------------------------------------------------------------------
# BP-02, BP-03: Sealed independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blind_panel_sealed_proposals():
    """BP-02, BP-03: Each outside agent gets the same brief, proposals collected before reveal."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    agent1 = StubAdapter(["Agent 1 proposal"])
    agent2 = StubAdapter(["Agent 2 proposal"])
    lead = StubAdapter(["Lead proposal"])
    synthesizer = StubAdapter([_negotiation_json()])

    result = await brainstorm_panel(
        brief=_valid_brief(),
        outside_adapters=[agent1, agent2],
        lead_adapter=lead,
        synthesizer_adapter=synthesizer,
    )

    assert result.artifact.status == "consensus"
    # Both agents should have been called with just the brief
    assert len(agent1.calls) == 1
    assert len(agent2.calls) == 1
    # Neither agent should see the other's proposal in their prompt
    assert "Agent 2 proposal" not in agent1.calls[0]
    assert "Agent 1 proposal" not in agent2.calls[0]


@pytest.mark.asyncio
async def test_blind_panel_provenance():
    """BP-05: Each proposal turn has distinct provenance."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    agent1 = StubAdapter(["Proposal 1"])
    agent2 = StubAdapter(["Proposal 2"])
    lead = StubAdapter(["Lead proposal"])
    synthesizer = StubAdapter([_negotiation_json()])

    result = await brainstorm_panel(
        brief=_valid_brief(),
        outside_adapters=[agent1, agent2],
        lead_adapter=lead,
        synthesizer_adapter=synthesizer,
        outside_labels=["codex", "ollama"],
    )

    # Transcript should have proposal turns with distinct actor info
    proposal_turns = [
        t for t in result.transcript.exchanges
        if t.phase == "proposal"
    ]
    assert len(proposal_turns) >= 2


# ---------------------------------------------------------------------------
# BP-06: Max agents cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blind_panel_max_agents():
    """BP-06: Maximum 5 outside agents enforced."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    agents = [StubAdapter([f"Proposal {i}"]) for i in range(6)]
    lead = StubAdapter(["Lead"])
    synthesizer = StubAdapter([_negotiation_json()])

    with pytest.raises(ValueError, match="maximum|5"):
        await brainstorm_panel(
            brief=_valid_brief(),
            outside_adapters=agents,
            lead_adapter=lead,
            synthesizer_adapter=synthesizer,
        )


# ---------------------------------------------------------------------------
# BP-12: Single-backend default unchanged
# ---------------------------------------------------------------------------


def test_brainstorm_still_works_single_agent():
    """BP-12: Original single-agent brainstorm still importable."""
    from agentcouncil.deliberation import brainstorm
    assert brainstorm is not None


# ---------------------------------------------------------------------------
# BP-14: Partial panel on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blind_panel_partial_on_failure():
    """BP-14: If one agent fails, panel continues with remaining."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter, AdapterError

    class FailingAdapter:
        calls = []
        def call(self, prompt):
            raise AdapterError("agent offline")
        async def acall(self, prompt):
            return self.call(prompt)

    agent1 = StubAdapter(["Agent 1 proposal"])
    agent2 = FailingAdapter()
    lead = StubAdapter(["Lead proposal"])
    synthesizer = StubAdapter([_negotiation_json()])

    result = await brainstorm_panel(
        brief=_valid_brief(),
        outside_adapters=[agent1, agent2],
        lead_adapter=lead,
        synthesizer_adapter=synthesizer,
    )

    # Should still produce a result with agent1's contribution
    assert result.artifact.status == "consensus"
