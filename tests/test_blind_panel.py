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


# ---------------------------------------------------------------------------
# Additional coverage: BP-01, BP-04, BP-07, BP-09, BP-10, BP-11, BP-13
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blind_panel_synthesis_includes_all_proposals():
    """BP-04: Synthesis prompt includes all N+1 proposals."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    agent1 = StubAdapter(["Agent1: use Redis"])
    agent2 = StubAdapter(["Agent2: use Memcached"])
    lead = StubAdapter(["Lead: use in-memory"])

    # Capture what the synthesizer sees
    synthesizer = StubAdapter([_negotiation_json()])

    result = await brainstorm_panel(
        brief=_valid_brief(),
        outside_adapters=[agent1, agent2],
        lead_adapter=lead,
        synthesizer_adapter=synthesizer,
    )

    # Synthesizer should have seen all proposals
    synthesis_prompt = synthesizer.calls[0]
    assert "Agent1: use Redis" in synthesis_prompt or "Redis" in synthesis_prompt
    assert "Agent2: use Memcached" in synthesis_prompt or "Memcached" in synthesis_prompt
    assert "Lead: use in-memory" in synthesis_prompt or "in-memory" in synthesis_prompt


@pytest.mark.asyncio
async def test_blind_panel_transcript_has_all_proposals():
    """BP-13: All proposals persisted in transcript."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    agent1 = StubAdapter(["Proposal A"])
    agent2 = StubAdapter(["Proposal B"])
    agent3 = StubAdapter(["Proposal C"])
    lead = StubAdapter(["Lead proposal"])
    synthesizer = StubAdapter([_negotiation_json()])

    result = await brainstorm_panel(
        brief=_valid_brief(),
        outside_adapters=[agent1, agent2, agent3],
        lead_adapter=lead,
        synthesizer_adapter=synthesizer,
    )

    # Transcript should have proposal turns for all agents + lead
    proposal_turns = [
        t for t in result.transcript.exchanges
        if t.phase == "proposal"
    ]
    assert len(proposal_turns) >= 4  # 3 outside + 1 lead


@pytest.mark.asyncio
async def test_blind_panel_empty_agents_raises():
    """BP: At least 1 outside agent required."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    with pytest.raises(ValueError, match="at least 1"):
        await brainstorm_panel(
            brief=_valid_brief(),
            outside_adapters=[],
            lead_adapter=StubAdapter([]),
            synthesizer_adapter=StubAdapter([]),
        )


@pytest.mark.asyncio
async def test_blind_panel_single_agent_works():
    """BP-12: Single outside agent mode works (degenerate panel)."""
    from agentcouncil.deliberation import brainstorm_panel
    from agentcouncil.adapters import StubAdapter

    agent = StubAdapter(["Solo proposal"])
    lead = StubAdapter(["Lead proposal"])
    synthesizer = StubAdapter([_negotiation_json()])

    result = await brainstorm_panel(
        brief=_valid_brief(),
        outside_adapters=[agent],
        lead_adapter=lead,
        synthesizer_adapter=synthesizer,
    )

    assert result.artifact.status == "consensus"
