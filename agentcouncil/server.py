from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import uuid
from pathlib import Path

logging.basicConfig(
    level=getattr(logging, os.environ.get("AGENTCOUNCIL_LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from fastmcp import FastMCP

from agentcouncil.adapters import (
    ClaudeAdapter,
    resolve_outside_adapter, resolve_outside_backend,
)
from agentcouncil.config import ProfileLoader, BackendProfile
from agentcouncil.session import OutsideSession, OutsideSessionAdapter
from agentcouncil.runtime import OutsideRuntime
from agentcouncil.brief import Brief, BriefBuilder, CodeExcerpt, ContaminatedBriefError, CONTAMINATION_PATTERNS
from agentcouncil.challenge import challenge
from agentcouncil.deliberation import brainstorm
from agentcouncil.decide import decide
from agentcouncil.review import review
from agentcouncil.schemas import ChallengeInput, DecideInput, DecideOption, ReviewInput, TranscriptMeta
from agentcouncil.certifier import CertificationCache, check_certification_gate
from agentcouncil.providers.base import OutsideProvider, ProviderError
from agentcouncil.runtime import OutsideRuntime
from agentcouncil.session import OutsideSession
from agentcouncil.schemas import JournalEntry
from agentcouncil.autopilot.orchestrator import LinearOrchestrator
from agentcouncil.autopilot.run import AutopilotRun, StageCheckpoint, persist, load_run, resume, validate_transition
from agentcouncil.autopilot.loader import load_default_registry
from agentcouncil.autopilot.artifacts import SpecArtifact
from agentcouncil.autopilot.prep import run_spec_prep
from agentcouncil.autopilot.verify import run_verify
from agentcouncil.autopilot.ship import run_ship

__all__ = ["mcp", "_SESSIONS", "_make_provider"]

# Module-level FastMCP instance — exported for in-process test import.
# No adapters instantiated here (pitfall 3: EnvironmentError at import time).
mcp = FastMCP("agentcouncil", version="0.2.0")

# ---------------------------------------------------------------------------
# Session registry — maps session_id (UUID str) -> OutsideSession
# Per-session locks prevent concurrent replies/closes from racing.
# ---------------------------------------------------------------------------

_SESSIONS: dict[str, OutsideSession] = {}
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


def _make_provider(
    profile: str | None = None,
    model: str | None = None,
) -> OutsideProvider:
    """Resolve a named profile and instantiate the appropriate provider.

    Args:
        profile — Named profile from .agentcouncil.json. If None, falls back
                  to the default profile. Legacy string results of "codex" or
                  "claude" are dispatched directly to their respective providers
                  (UPROV-03). Other legacy strings raise ValueError.
        model   — Optional model override (takes precedence over profile.model).

    Returns:
        An OutsideProvider instance ready for use with OutsideRuntime.
        Recognised providers: ollama, openrouter, bedrock, kiro, codex, claude.

    Raises:
        ValueError: if the resolved result is an unrecognised legacy backend string.
        ProviderError: if the provider name in BackendProfile is unrecognised.
    """
    resolved = ProfileLoader().resolve(profile_name=profile)

    if isinstance(resolved, str):
        # UPROV-03: dispatch codex/claude from legacy string results
        if resolved == "codex":
            if shutil.which("codex") is None:
                raise ProviderError(
                    "codex binary not found on PATH. "
                    "Install from https://docs.openai.com/codex — "
                    "or configure a different backend in .agentcouncil.json."
                )
            from agentcouncil.providers.codex import CodexProvider
            return CodexProvider(model=model, cwd=str(Path.cwd()))
        elif resolved == "claude":
            if shutil.which("claude") is None:
                raise ProviderError(
                    "claude binary not found on PATH. "
                    "Install from https://docs.anthropic.com/claude-code — "
                    "or configure a different backend in .agentcouncil.json."
                )
            from agentcouncil.providers.claude import ClaudeProvider
            return ClaudeProvider(model=model)
        raise ValueError(
            f"Session API requires a named profile with provider=ollama/openrouter/bedrock/codex/claude. "
            f"Got legacy backend: {resolved!r}"
        )

    bp: BackendProfile = resolved

    if bp.provider == "ollama":
        from agentcouncil.providers.ollama import OllamaProvider
        return OllamaProvider(
            model=model or bp.model or "llama3",
            base_url=bp.endpoint or "http://localhost:11434",
        )
    elif bp.provider == "openrouter":
        from agentcouncil.providers.openrouter import OpenRouterProvider
        return OpenRouterProvider(
            model=model or bp.model or "openai/gpt-4o",
            api_key_env=bp.api_key_env or "OPENROUTER_API_KEY",
        )
    elif bp.provider == "bedrock":
        from agentcouncil.providers.bedrock import BedrockProvider
        return BedrockProvider(
            model=model or bp.model or "anthropic.claude-3-5-sonnet-20241022-v2:0",
        )
    elif bp.provider == "kiro":
        from agentcouncil.providers.kiro import KiroProvider
        return KiroProvider(
            cli_path=bp.cli_path,
            workspace=str(Path.cwd()),
        )
    elif bp.provider == "codex":
        if shutil.which("codex") is None:
            raise ProviderError(
                "codex binary not found on PATH. "
                "Install from https://docs.openai.com/codex — "
                "or configure a different backend in .agentcouncil.json."
            )
        from agentcouncil.providers.codex import CodexProvider
        return CodexProvider(
            model=model or bp.model,
            cwd=str(Path.cwd()),
        )
    elif bp.provider == "claude":
        if shutil.which("claude") is None:
            raise ProviderError(
                "claude binary not found on PATH. "
                "Install from https://docs.anthropic.com/claude-code — "
                "or configure a different backend in .agentcouncil.json."
            )
        from agentcouncil.providers.claude import ClaudeProvider
        return ClaudeProvider(
            model=model or bp.model,
        )
    else:
        raise ProviderError(f"Unknown provider: {bp.provider!r}")


def _build_meta(outside_backend: str, outside_transport: str) -> TranscriptMeta:
    """Build transcript metadata for provenance tracking."""
    lead_backend = "claude"
    return TranscriptMeta(
        lead_backend=lead_backend,
        lead_model="opus",
        outside_backend=outside_backend,
        outside_model=None,  # resolved at adapter level
        outside_transport=outside_transport,
        independence_tier=(
            "cross_backend" if outside_backend != lead_backend
            else "same_backend_fresh_session"
        ),
    )


@mcp.tool(name="outside_start")
async def outside_start_tool(
    prompt: str,
    profile: str | None = None,
    model: str | None = None,
) -> dict:
    """Start a multi-turn session with an outside LLM backend.

    Returns session_id and first response. Sessions are in-process only --
    server restart clears all sessions.

    Args:
        prompt  — First message to send to the outside backend.
        profile — Named backend profile from .agentcouncil.json.
        model   — Optional model override (takes precedence over profile.model).

    Returns:
        Dict with "session_id" (UUID string) and "response" (str).
    """
    provider = _make_provider(profile, model)

    # Resolve the BackendProfile to get provider_name for session metadata
    resolved = ProfileLoader().resolve(profile_name=profile)
    provider_name = resolved.provider if isinstance(resolved, BackendProfile) else resolved

    runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
    session = OutsideSession(
        provider,
        runtime,
        profile=profile,
        model=model,
        provider_name=provider_name,
    )
    try:
        await session.open()
        response = await session.call(prompt)
    except Exception:
        await provider.close()
        await session.close()
        raise
    session_id = str(uuid.uuid4())
    _SESSIONS[session_id] = session
    _SESSION_LOCKS[session_id] = asyncio.Lock()
    return {"session_id": session_id, "response": response}


@mcp.tool(name="outside_reply")
async def outside_reply_tool(
    session_id: str,
    prompt: str,
) -> dict:
    """Continue an existing outside session. Returns next response.

    Args:
        session_id — UUID string returned by outside_start.
        prompt     — Next message to send.

    Returns:
        Dict with "response" (str).

    Raises:
        ValueError: if session_id is not found in the registry.
    """
    if session_id not in _SESSIONS:
        raise ValueError(
            f"Unknown session_id: {session_id!r}. "
            f"Session may have expired or server was restarted."
        )
    lock = _SESSION_LOCKS.get(session_id)
    if lock:
        async with lock:
            if session_id not in _SESSIONS:
                raise ValueError(f"Session {session_id!r} was closed concurrently.")
            session = _SESSIONS[session_id]
            response = await session.call(prompt)
            return {"response": response}
    else:
        session = _SESSIONS[session_id]
        response = await session.call(prompt)
        return {"response": response}


@mcp.tool(name="outside_close")
async def outside_close_tool(
    session_id: str,
) -> dict:
    """Close an outside session and free resources.

    Args:
        session_id — UUID string returned by outside_start.

    Returns:
        Dict with "status": "closed" and "session_id".

    Raises:
        ValueError: if session_id is not found in the registry.
    """
    if session_id not in _SESSIONS:
        raise ValueError(
            f"Unknown session_id: {session_id!r}. "
            f"Session may have expired or server was restarted."
        )
    # Acquire lock BEFORE removing from registry to prevent reply/close race
    lock = _SESSION_LOCKS.get(session_id)
    if lock:
        async with lock:
            _SESSION_LOCKS.pop(session_id, None)
            session = _SESSIONS.pop(session_id, None)
            if session:
                await session._provider.close()
                await session.close()
    else:
        session = _SESSIONS.pop(session_id, None)
        if session:
            await session._provider.close()
            await session.close()
    return {"status": "closed", "session_id": session_id}


@mcp.tool(name="get_outside_backend_info")
def get_outside_backend_info_tool(
    profile: str | None = None,
    model: str | None = None,
) -> dict:
    """Get capability flags for a backend profile without opening a session.

    Does not call auth_check or create any session. Safe to call at any time
    to inspect what a profile would provide.

    Args:
        profile — Named backend profile. If None, uses default profile or legacy fallback.
        model   — Optional model override (used in the returned "model" field).

    Returns:
        Dict with: provider, model, session_strategy, workspace_access, supports_runtime_tools.
    """
    try:
        provider = _make_provider(profile, model)
    except (ValueError, ProviderError):
        # Legacy fallback for unresolvable profiles
        resolved = ProfileLoader().resolve(profile_name=profile)
        provider_name = resolved if isinstance(resolved, str) else resolved.provider
        return {
            "provider": provider_name,
            "model": model,
            "session_strategy": "replay",
            "workspace_access": "assisted",
            "supports_runtime_tools": True,
        }

    resolved = ProfileLoader().resolve(profile_name=profile)
    provider_name = resolved if isinstance(resolved, str) else resolved.provider
    effective_model = model
    if not isinstance(resolved, str):
        effective_model = model or resolved.model

    return {
        "provider": provider_name,
        "model": effective_model,
        "session_strategy": provider.session_strategy,
        "workspace_access": provider.workspace_access,
        "supports_runtime_tools": provider.supports_runtime_tools,
    }


@mcp.tool(name="brainstorm")
async def brainstorm_tool(
    context: str,
    code_context: str | None = None,
    rounds: int = 1,
    backend: str | None = None,
    outside_agent: str | None = None,
    backends: list[str] | None = None,
) -> dict:
    """Run the AgentCouncil deliberation protocol and return a consensus artifact.

    Convenes an outside agent and a lead agent (Claude) to independently
    propose solutions, then negotiate a structured consensus. The outside agent sees
    only the brief, ensuring independence before convergence.

    Args:
        context: Free-form problem description, background, constraints, and goals.
            Passed directly to the outside agent as the problem statement. Scanned
            for contamination (opinion language) before sending. Do not include your
            proposed solution — the protocol depends on independent thinking first.
            When code_context is provided, a structured brief is extracted via LLM.
        code_context: Optional verbatim code or file content for code-aware briefs.
            When provided, triggers full LLM brief extraction (structured fields).
            Not scanned for contamination (caller-supplied verbatim content).
        rounds: Number of negotiation rounds (default 1). Higher values give agents
            more back-and-forth discussion before the final synthesis. rounds=1 is the
            original single-shot negotiation. rounds=2 adds one exchange pair before
            synthesis. rounds=3 adds two exchange pairs, etc. Each extra round adds
            ~2-4 minutes of wall time.
        backend: Named backend profile or legacy backend string ("codex"/"claude").
            Defaults to AGENTCOUNCIL_OUTSIDE_AGENT env var, then "claude".
        outside_agent: Deprecated alias for backend. Use backend= instead.

    Returns:
        BrainstormResult as a dict with two top-level keys:
        - 'artifact': ConsensusArtifact with recommended_direction, agreement_points,
          disagreement_points, rejected_alternatives, open_risks, next_action, status.
        - 'transcript': Transcript with input_prompt, outside_initial,
          lead_initial, exchanges (back-and-forth discussion),
          final_output, and meta (backend provenance).
    """
    import time as _time
    _t0 = _time.time()

    effective_backend = backend or outside_agent
    lead = ClaudeAdapter(model="opus", timeout=300)

    # BP-01: Multi-agent Blind Panel mode
    if backends and len(backends) > 1:
        from agentcouncil.deliberation import brainstorm_panel
        # Build brief first
        if code_context is not None:
            brief_adapter = ClaudeAdapter(model="haiku", timeout=60)
            builder = BriefBuilder(adapter=brief_adapter)
            excerpts = [CodeExcerpt(path="caller-supplied", content=code_context)]
            brief = builder.build(context, code_context=excerpts)
        else:
            brief = Brief(problem_statement=context, background="", constraints=[], goals=[], open_questions=[])

        # Create adapters for each backend
        outside_adapters = []
        sessions_to_close = []
        try:
            for bk in backends:
                provider = _make_provider(profile=bk)
                runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
                session = OutsideSession(provider, runtime, profile=bk)
                await session.open()
                outside_adapters.append(OutsideSessionAdapter(session))
                sessions_to_close.append((provider, session))

            synthesizer = ClaudeAdapter(model="opus", timeout=300)
            result = await brainstorm_panel(
                brief=brief,
                outside_adapters=outside_adapters,
                lead_adapter=lead,
                synthesizer_adapter=synthesizer,
                outside_labels=backends,
            )
        finally:
            for prov, sess in sessions_to_close:
                await prov.close()
                await sess.close()

        _persist_journal("brainstorm", result, _t0)
        return result.model_dump()

    if code_context is not None:
        # Complex context with code — use BriefBuilder to extract structure.
        brief_adapter = ClaudeAdapter(model="haiku", timeout=60)
        builder = BriefBuilder(adapter=brief_adapter)
        excerpts = [CodeExcerpt(path="caller-supplied", content=code_context)]
        brief = builder.build(context, code_context=excerpts)
    else:
        # Simple query — skip LLM brief extraction but still run contamination scan.
        import re
        for pattern in CONTAMINATION_PATTERNS:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                raise ContaminatedBriefError(
                    f"Context contains opinion language: '{match.group()}'. "
                    f"Remove your proposed solution from the context."
                )
        brief = Brief(
            problem_statement=context,
            background="",
            constraints=[],
            goals=[],
            open_questions=[],
        )

    try:
        provider = _make_provider(profile=effective_backend)
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        bp = ProfileLoader().resolve(profile_name=effective_backend)
        provider_name = bp.provider if isinstance(bp, BackendProfile) else str(bp)
        session = OutsideSession(
            provider, runtime,
            profile=effective_backend, model=None, provider_name=provider_name,
        )
        await session.open()
        try:
            outside = OutsideSessionAdapter(session)
            meta = TranscriptMeta(
                lead_backend="claude",
                lead_model="opus",
                outside_backend=provider_name,
                outside_model=session.model,
                outside_transport="session",
                independence_tier="cross_backend",
                outside_provider=session.provider_name,
                outside_profile=session.profile,
                outside_session_mode=session.session_mode,
                outside_workspace_access=session.workspace_access,
            )
            result = await brainstorm(
                brief=brief,
                outside_adapter=outside,
                lead_adapter=lead,
                negotiation_rounds=max(1, rounds),
                outside_meta=meta,
            )
        finally:
            await provider.close()
            await session.close()
    except ValueError:
        # Legacy backend (codex/claude) — fall back to existing adapter path
        backend_str = resolve_outside_backend(effective_backend)
        outside = resolve_outside_adapter(effective_backend, timeout=300)
        meta = _build_meta(backend_str, "subprocess")
        result = await brainstorm(
            brief=brief,
            outside_adapter=outside,
            lead_adapter=lead,
            negotiation_rounds=max(1, rounds),
        )
        result.transcript.meta = meta

    _persist_journal("brainstorm", result, _t0)
    return result.model_dump()


@mcp.tool(name="review")
async def review_tool(
    artifact: str,
    artifact_type: str = "other",
    review_objective: str | None = None,
    focus_areas: list[str] | None = None,
    rounds: int = 1,
    backend: str | None = None,
    outside_agent: str | None = None,
) -> dict:
    """Run the AgentCouncil review protocol and return a structured review artifact.

    Convenes an outside agent and a lead agent (Claude) to independently
    review an artifact, then synthesize findings. Both agents see only the factual
    context -- no opinion or assessment is shared in the brief.

    Findings are evaluative only: they describe impact, not fixes.

    Args:
        artifact: The text content to review (code, design doc, plan, etc.).
        artifact_type: Type of artifact: "code", "design", "plan", "document", or "other".
            Defaults to "other".
        review_objective: Optional objective for the review (e.g. "security audit").
        focus_areas: Optional list of areas to focus on (e.g. ["input validation", "auth"]).
        rounds: Number of exchange rounds (default 1). Higher values give agents more
            discussion before synthesis. rounds=1 means no exchanges (initial + synthesis).
        backend: Named backend profile or legacy backend string ("codex"/"claude").
            Defaults to AGENTCOUNCIL_OUTSIDE_AGENT env var, then "claude".
        outside_agent: Deprecated alias for backend. Use backend= instead.

    Returns:
        DeliberationResult as a dict with three top-level keys:
        - 'deliberation_status': ConsensusStatus value.
        - 'artifact': ReviewArtifact with verdict, summary, findings[], strengths[],
          open_questions[], next_action.
        - 'transcript': Transcript with input_prompt, outside_initial, lead_initial,
          exchanges, final_output, and meta (backend provenance).
    """
    import time as _time
    _t0 = _time.time()

    # R2-01: Create journal session at protocol start
    _journal_sid = _create_journal_session("review", _t0)

    # R3-01: Mutable checkpoint state — later phases merge into this, never replace
    _cp_state: dict = {
        "protocol_type": "review",
        "input_prompt": "",
        "outside_initial": None,
        "lead_initial": None,
        "accumulated_turns": [],
        "exchange_rounds_completed": 0,
        "exchange_rounds_total": max(1, rounds),
        "provider_config": {"profile": backend or outside_agent},
        "artifact_cls_name": "ReviewArtifact",
    }

    def _checkpoint_cb(phase: str, data: dict) -> None:
        """Persist checkpoint to journal during execution (R3-01: merge, don't replace)."""
        if _journal_sid:
            try:
                from agentcouncil.workflow import ProtocolCheckpoint, ProtocolPhase, save_checkpoint
                # Merge new data into accumulated state
                if "input_prompt" in data and data["input_prompt"]:
                    _cp_state["input_prompt"] = data["input_prompt"]
                if "outside_initial" in data:
                    _cp_state["outside_initial"] = data["outside_initial"]
                if "lead_initial" in data:
                    _cp_state["lead_initial"] = data["lead_initial"]
                if "round" in data:
                    _cp_state["exchange_rounds_completed"] = data["round"]
                if "accumulated_turns" in data:
                    _cp_state["accumulated_turns"] = data["accumulated_turns"]

                cp = ProtocolCheckpoint(
                    current_phase=ProtocolPhase(phase),
                    **_cp_state,
                )
                save_checkpoint(_journal_sid, cp)
            except Exception:
                pass  # Non-fatal

    effective_backend = backend or outside_agent

    # Certification gate: block prompt-only models from review (CERT-04)
    try:
        _bp = ProfileLoader().resolve(profile_name=effective_backend)
        _gate_model = _bp.model if isinstance(_bp, BackendProfile) else None
    except Exception:
        _gate_model = None
    check_certification_gate("review", model_id=_gate_model, profile=effective_backend, cache=CertificationCache())

    lead = ClaudeAdapter(model="opus", timeout=300)

    review_input = ReviewInput(
        artifact=artifact,
        artifact_type=artifact_type,
        review_objective=review_objective,
        focus_areas=focus_areas or [],
        rounds=max(1, rounds),
    )

    try:
        provider = _make_provider(profile=effective_backend)
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        bp = ProfileLoader().resolve(profile_name=effective_backend)
        provider_name = bp.provider if isinstance(bp, BackendProfile) else str(bp)
        session = OutsideSession(
            provider, runtime,
            profile=effective_backend, model=None, provider_name=provider_name,
        )
        await session.open()
        try:
            outside = OutsideSessionAdapter(session)
            meta = TranscriptMeta(
                lead_backend="claude",
                lead_model="opus",
                outside_backend=provider_name,
                outside_model=session.model,
                outside_transport="session",
                independence_tier="cross_backend",
                outside_provider=session.provider_name,
                outside_profile=session.profile,
                outside_session_mode=session.session_mode,
                outside_workspace_access=session.workspace_access,
            )
            result = await review(review_input, outside, lead, outside_meta=meta, checkpoint_callback=_checkpoint_cb)
        finally:
            await provider.close()
            await session.close()
    except ValueError:
        # Legacy backend (codex/claude) — fall back to existing adapter path
        backend_str = resolve_outside_backend(effective_backend)
        outside = resolve_outside_adapter(effective_backend, timeout=300)
        meta = _build_meta(backend_str, "subprocess")
        result = await review(review_input, outside, lead, checkpoint_callback=_checkpoint_cb)
        result.transcript.meta = meta

    _persist_journal("review", result, _t0, session_id=_journal_sid)
    return result.model_dump()


@mcp.tool(name="decide")
async def decide_tool(
    decision: str,
    options: list[dict],
    criteria: str | None = None,
    constraints: str | None = None,
    rounds: int = 1,
    backend: str | None = None,
    outside_agent: str | None = None,
) -> dict:
    """Run the AgentCouncil decide protocol and return a structured decision artifact.

    Convenes an outside agent and a lead agent (Claude) to independently
    evaluate a set of options, then synthesize a structured comparison. Both agents
    see only factual context -- no preference or ranking is shared in the brief.

    Agents evaluate ONLY the caller-provided options. They cannot invent new ones.

    Args:
        decision: The decision question to evaluate (e.g. "Which database should we use?").
        options: List of options to evaluate. Each dict must have 'id', 'label', 'description'.
            Minimum 2 options required.
        criteria: Optional evaluation criteria (e.g. "Performance and cost").
        constraints: Optional constraints (e.g. "Must be open source").
        rounds: Number of exchange rounds (default 1). Higher values give agents more
            discussion before synthesis.
        backend: Named backend profile or legacy backend string ("codex"/"claude").
            Defaults to AGENTCOUNCIL_OUTSIDE_AGENT env var, then "claude".
        outside_agent: Deprecated alias for backend. Use backend= instead.

    Returns:
        DeliberationResult as a dict with three top-level keys:
        - 'deliberation_status': ConsensusStatus value.
        - 'artifact': DecideArtifact with outcome, winner_option_id, decision_summary,
          option_assessments[], defer_reason, experiment_plan, revisit_triggers[], next_action.
        - 'transcript': Transcript with input_prompt, outside_initial, lead_initial,
          exchanges, final_output, and meta (backend provenance).
    """
    import time as _time
    _t0 = _time.time()

    effective_backend = backend or outside_agent
    lead = ClaudeAdapter(model="opus", timeout=300)

    decide_options = [DecideOption(**opt) for opt in options]
    decide_input = DecideInput(
        decision=decision,
        options=decide_options,
        criteria=criteria,
        constraints=constraints,
        rounds=max(1, rounds),
    )

    try:
        provider = _make_provider(profile=effective_backend)
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        bp = ProfileLoader().resolve(profile_name=effective_backend)
        provider_name = bp.provider if isinstance(bp, BackendProfile) else str(bp)
        session = OutsideSession(
            provider, runtime,
            profile=effective_backend, model=None, provider_name=provider_name,
        )
        await session.open()
        try:
            outside = OutsideSessionAdapter(session)
            meta = TranscriptMeta(
                lead_backend="claude",
                lead_model="opus",
                outside_backend=provider_name,
                outside_model=session.model,
                outside_transport="session",
                independence_tier="cross_backend",
                outside_provider=session.provider_name,
                outside_profile=session.profile,
                outside_session_mode=session.session_mode,
                outside_workspace_access=session.workspace_access,
            )
            result = await decide(decide_input, outside, lead, outside_meta=meta)
        finally:
            await provider.close()
            await session.close()
    except ValueError:
        # Legacy backend (codex/claude) — fall back to existing adapter path
        backend_str = resolve_outside_backend(effective_backend)
        outside = resolve_outside_adapter(effective_backend, timeout=300)
        meta = _build_meta(backend_str, "subprocess")
        result = await decide(decide_input, outside, lead)
        result.transcript.meta = meta

    _persist_journal("decide", result, _t0)
    return result.model_dump()


@mcp.tool(name="challenge")
async def challenge_tool(
    artifact: str,
    assumptions: list[str] | None = None,
    success_criteria: str | None = None,
    constraints: str | None = None,
    rounds: int = 2,
    backend: str | None = None,
    outside_agent: str | None = None,
    specialist_provider: str | None = None,
) -> dict:
    """Run the AgentCouncil challenge protocol -- adversarial stress-testing.

    Convenes an outside agent as attacker and a lead agent (Claude) as
    defender to independently analyze a plan/design, then synthesize findings.
    The outside agent attacks assumptions and finds failure modes. The lead agent
    defends. Neither sees the other's initial analysis before producing their own.

    Challenge is adversarial only: it finds failure modes, attacks assumptions,
    and returns a readiness verdict. It does NOT propose repairs or fixes.

    Args:
        artifact: The plan, design, or approach to stress-test.
        assumptions: Optional list of assumptions to attack.
        success_criteria: Optional success criteria for the plan.
        constraints: Optional constraints on the plan.
        rounds: Number of exchange rounds (default 2). rounds=2 means 1 exchange
            pair before synthesis. Higher values give more attack/defense rounds.
        backend: Named backend profile or legacy backend string ("codex"/"claude").
            Defaults to AGENTCOUNCIL_OUTSIDE_AGENT env var, then "claude".
        outside_agent: Deprecated alias for backend. Use backend= instead.

    Returns:
        DeliberationResult as a dict with three top-level keys:
        - 'deliberation_status': ConsensusStatus value.
        - 'artifact': ChallengeArtifact with readiness, summary, failure_modes[],
          surviving_assumptions[], break_conditions[], residual_risks[], next_action.
        - 'transcript': Transcript with input_prompt, outside_initial, lead_initial,
          exchanges, final_output, and meta (backend provenance).
    """
    import time as _time
    _t0 = _time.time()

    effective_backend = backend or outside_agent

    # Certification gate: block prompt-only models from challenge (CERT-04)
    try:
        _bp = ProfileLoader().resolve(profile_name=effective_backend)
        _gate_model = _bp.model if isinstance(_bp, BackendProfile) else None
    except Exception:
        _gate_model = None
    check_certification_gate("challenge", model_id=_gate_model, profile=effective_backend, cache=CertificationCache())

    lead = ClaudeAdapter(model="opus", timeout=300)

    challenge_input = ChallengeInput(
        artifact=artifact,
        assumptions=assumptions or [],
        success_criteria=success_criteria,
        constraints=constraints,
        rounds=max(1, rounds),
    )

    try:
        provider = _make_provider(profile=effective_backend)
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        bp = ProfileLoader().resolve(profile_name=effective_backend)
        provider_name = bp.provider if isinstance(bp, BackendProfile) else str(bp)
        session = OutsideSession(
            provider, runtime,
            profile=effective_backend, model=None, provider_name=provider_name,
        )
        await session.open()
        try:
            outside = OutsideSessionAdapter(session)
            meta = TranscriptMeta(
                lead_backend="claude",
                lead_model="opus",
                outside_backend=provider_name,
                outside_model=session.model,
                outside_transport="session",
                independence_tier="cross_backend",
                outside_provider=session.provider_name,
                outside_profile=session.profile,
                outside_session_mode=session.session_mode,
                outside_workspace_access=session.workspace_access,
            )
            result = await challenge(challenge_input, outside, lead, outside_meta=meta)
        finally:
            await provider.close()
            await session.close()
    except ValueError:
        # Legacy backend (codex/claude) — fall back to existing adapter path
        backend_str = resolve_outside_backend(effective_backend)
        outside = resolve_outside_adapter(effective_backend, timeout=300)
        meta = _build_meta(backend_str, "subprocess")
        result = await challenge(challenge_input, outside, lead)
        result.transcript.meta = meta

    _persist_journal("challenge", result, _t0)
    return result.model_dump()


@mcp.tool(name="outside_query")
async def outside_query_tool(
    prompt: str,
    outside_agent: str | None = None,
) -> str:
    """Send a single prompt to the outside agent and return the response.

    Deprecated: Use outside_start/outside_reply/outside_close instead.
    This tool will be removed in a future release.

    Low-level tool for skill-driven orchestration. The skill handles protocol
    logic (proposal ordering, exchanges, synthesis) while this tool handles
    backend resolution and adapter creation.

    Each call creates a fresh session — there is no session state between calls.

    Args:
        prompt: The prompt to send to the outside agent.
        outside_agent: Backend profile or legacy name. Defaults to env/config.

    Returns:
        The outside agent's response as plain text, with deprecation notice appended.
    """
    deprecation_notice = (
        "\n\n[DEPRECATED: outside_query is deprecated and will be removed in a future release. "
        "Use outside_start/outside_reply/outside_close instead.]"
    )
    try:
        provider = _make_provider(profile=outside_agent)
        resolved = ProfileLoader().resolve(profile_name=outside_agent)
        provider_name = resolved.provider if isinstance(resolved, BackendProfile) else resolved
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        session = OutsideSession(
            provider, runtime,
            profile=outside_agent, model=None, provider_name=provider_name,
        )
        try:
            await session.open()
            response = await session.call(prompt)
        finally:
            await provider.close()
            await session.close()
        return response + deprecation_notice
    except ValueError:
        # Legacy backend (unrecognised string) — fall back to adapter path
        adapter = resolve_outside_adapter(outside_agent, timeout=300)
        return adapter.call(prompt) + deprecation_notice


@mcp.tool(name="show-effective-config")
def show_effective_config_tool(
    profile: str | None = None,
) -> dict:
    """Report each resolved config value and its source level.

    Shows where each configuration value came from in the precedence
    stack: skill_arg > env_var > project_config > global_config > default.
    Also reports the legacy AGENTCOUNCIL_OUTSIDE_AGENT env var if set.

    Args:
        profile: Optional profile name to inspect. Reserved for future use —
            currently reports top-level config fields (default_profile, profiles).

    Returns:
        Dict mapping field names to {value, source} where source is one of:
        skill_arg, project_config, global_config, env_var, legacy_env_var, default.
    """
    loader = ProfileLoader()
    return loader.effective_report()


# ---------------------------------------------------------------------------
# Journal persistence (DJ-01, DJ-11)
# ---------------------------------------------------------------------------


def _create_journal_session(protocol_type: str, start_time: float) -> str | None:
    """Create a journal entry at protocol start so checkpoints can attach (R-02).

    Returns session_id on success, None on failure. Never raises.
    """
    try:
        from agentcouncil.journal import write_entry
        from agentcouncil.schemas import Transcript

        session_id = str(uuid.uuid4())
        entry = JournalEntry(
            session_id=session_id,
            protocol_type=protocol_type,
            start_time=start_time,
            end_time=0.0,
            status="consensus",
            artifact={},
            transcript=Transcript(input_prompt="(in progress)"),
        )
        write_entry(entry)
        return session_id
    except Exception as e:
        logging.warning("journal session create failed (non-fatal): %s", e)
        return None


def _persist_journal(
    protocol_type: str,
    result: object,
    start_time: float,
    session_id: str | None = None,
) -> None:
    """Persist a protocol result to the journal (DJ-01, DJ-11).

    If session_id is provided, updates the existing entry.
    Otherwise creates a new one. Never raises.
    """
    import time as _time

    try:
        from agentcouncil.journal import write_entry

        # Extract transcript and artifact from result
        result_dict = result.model_dump() if hasattr(result, "model_dump") else {}
        transcript_data = result_dict.get("transcript", {})
        artifact_data = result_dict.get("artifact", {})
        status_val = (
            result_dict.get("deliberation_status")
            or artifact_data.get("status")
            or "consensus"
        )

        from agentcouncil.schemas import Transcript

        transcript = Transcript.model_validate(transcript_data)

        # Extract title from first line of input prompt
        raw_prompt = transcript_data.get("input_prompt", "") or ""
        first_line = raw_prompt.strip().split("\n")[0].lstrip("# ").strip()
        title = first_line[:80] if first_line else None

        entry = JournalEntry(
            session_id=session_id or str(uuid.uuid4()),
            title=title,
            protocol_type=protocol_type,
            start_time=start_time,
            end_time=_time.time(),
            status=status_val,
            artifact=artifact_data,
            transcript=transcript,
        )
        write_entry(entry)
    except Exception as e:
        logging.warning("journal persist failed (non-fatal): %s", e)


@mcp.tool(name="protocol_resume")
async def protocol_resume_tool(
    session_id: str,
    profile: str | None = None,
    model: str | None = None,
) -> dict:
    """Resume a checkpointed protocol run from its last phase boundary.

    Reconstructs protocol state from the journal and continues execution.
    Returns the same artifact type as a fresh run (RP-09).

    Args:
        session_id: Journal session ID with saved checkpoint.
        profile: Optional backend profile for the outside agent.
        model: Optional model override.

    Returns:
        DeliberationResult as dict.

    Raises:
        ValueError: If session is unknown, has no checkpoint, or is completed.
    """
    from agentcouncil.workflow import resume_protocol

    lead = ClaudeAdapter(model="opus", timeout=300)

    try:
        provider = _make_provider(profile=profile, model=model)
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        session = OutsideSession(provider, runtime, profile=profile, model=model)
        await session.open()
        try:
            outside = OutsideSessionAdapter(session)
            result = await resume_protocol(session_id, outside, lead)
        finally:
            await provider.close()
            await session.close()
    except ValueError:
        backend_str = resolve_outside_backend(profile)
        outside = resolve_outside_adapter(profile, timeout=300)
        result = await resume_protocol(session_id, outside, lead)

    return result.model_dump()


@mcp.tool(name="review_loop")
async def review_loop_tool(
    artifact: str,
    artifact_type: str = "code",
    review_objective: str | None = None,
    focus_areas: list[str] | None = None,
    max_iterations: int = 3,
    backend: str | None = None,
) -> dict:
    """Run an iterative review convergence loop (CL-01).

    Reviews the artifact, tracks findings, and loops through fix/re-review
    cycles until all findings are verified or max iterations reached.

    Args:
        artifact: Text content to review.
        artifact_type: Type (code, design, plan, document, other).
        review_objective: Optional review focus.
        focus_areas: Optional specific areas.
        max_iterations: Maximum iterations (default 3, hard cap 10).
        backend: Backend profile for the outside reviewer.
    """
    import time as _time

    from agentcouncil.convergence import review_loop

    lead = ClaudeAdapter(model="opus", timeout=300)

    try:
        provider = _make_provider(profile=backend)
        runtime = OutsideRuntime(provider, workspace=str(Path.cwd()))
        session = OutsideSession(provider, runtime, profile=backend)
        await session.open()
        try:
            outside = OutsideSessionAdapter(session)
            result = await review_loop(
                artifact=artifact,
                artifact_type=artifact_type,
                outside_adapter=outside,
                lead_adapter=lead,
                review_objective=review_objective,
                focus_areas=focus_areas,
                max_iterations=max_iterations,
            )
        finally:
            await provider.close()
            await session.close()
    except ValueError:
        outside = resolve_outside_adapter(backend, timeout=300)
        result = await review_loop(
            artifact=artifact,
            artifact_type=artifact_type,
            outside_adapter=outside,
            lead_adapter=lead,
            review_objective=review_objective,
            focus_areas=focus_areas,
            max_iterations=max_iterations,
        )

    return result.model_dump()


@mcp.tool(name="journal_stream")
def journal_stream_tool(
    session_id: str,
    since_cursor: int | None = None,
) -> dict:
    """Stream events from a journal entry with cursor-based retrieval.

    Read-only. Returns events since the given cursor position.

    Args:
        session_id: UUID string of the session.
        since_cursor: Return events after this cursor. Omit for all events.

    Returns:
        Dict with 'events' (list) and 'next_cursor' (int).
    """
    from agentcouncil.journal import stream_events

    return stream_events(session_id, since_cursor=since_cursor)


@mcp.tool(name="journal_list")
def journal_list_tool(
    limit: int = 20,
    protocol: str | None = None,
) -> list[dict]:
    """List recent deliberation journal entries.

    Returns metadata (not full transcripts) sorted by start_time descending.

    Args:
        limit: Maximum entries to return (default 20).
        protocol: Filter by protocol type (brainstorm, review, decide, challenge).
    """
    from agentcouncil.journal import list_entries

    return list_entries(limit=limit, protocol=protocol)


@mcp.tool(name="journal_get")
def journal_get_tool(session_id: str) -> dict:
    """Retrieve a full journal entry by session_id.

    Args:
        session_id: UUID string of the session to retrieve.

    Returns:
        Full JournalEntry as dict including transcript and artifact.

    Raises:
        ValueError: If session_id is unknown.
    """
    from agentcouncil.journal import read_entry

    return read_entry(session_id).model_dump()


@mcp.tool(name="autopilot_prepare")
def autopilot_prepare_tool(intent: str, spec_id: str, title: str, objective: str,
                            requirements: list[str], acceptance_criteria: list[str],
                            tier: int = 2) -> dict:
    """Initialize an autopilot run: validate spec, create run state, persist to disk.

    Call this before autopilot_start. Returns a run_id to use with other tools.
    """
    import time as _time
    import uuid as _uuid

    # Validate spec via SpecArtifact model
    spec = SpecArtifact(spec_id=spec_id, title=title, objective=objective,
                        requirements=requirements, acceptance_criteria=acceptance_criteria)

    run_id = f"run-{_uuid.uuid4().hex[:12]}"
    stages = [
        StageCheckpoint(stage_name=name, status="pending")
        for name in ["spec_prep", "plan", "build", "verify", "ship"]
    ]
    run = AutopilotRun(
        run_id=run_id, spec_id=spec_id, status="running",
        current_stage="spec_prep", tier=tier, stages=stages,
        started_at=_time.time(), updated_at=_time.time(),
    )
    persist(run)
    return {"run_id": run.run_id, "status": run.status, "current_stage": run.current_stage, "tier": run.tier}


@mcp.tool(name="autopilot_start")
def autopilot_start_tool(run_id: str) -> dict:
    """Execute the full autopilot pipeline from current stage.

    The run must have been created via autopilot_prepare first.
    Returns the final run state. Uses real runners for spec_prep, verify, and ship stages.
    Plan and build stages use stub runners.
    """
    run = load_run(run_id)
    if run.status == "completed":
        return {"run_id": run.run_id, "status": run.status, "message": "Run already completed"}

    registry = load_default_registry()
    orchestrator = LinearOrchestrator(
        registry=registry,
        runners={"spec_prep": run_spec_prep, "verify": run_verify, "ship": run_ship},
    )
    result = orchestrator.run_pipeline(run)
    return {
        "run_id": result.run_id, "status": result.status,
        "current_stage": result.current_stage,
        "completed_at": result.completed_at,
        "stages": [{"stage": s.stage_name, "status": s.status} for s in result.stages],
    }


@mcp.tool(name="autopilot_status")
def autopilot_status_tool(run_id: str) -> dict:
    """Return the current state of an autopilot run."""
    run = load_run(run_id)
    return {
        "run_id": run.run_id, "status": run.status,
        "current_stage": run.current_stage, "tier": run.tier,
        "stages": [{"stage": s.stage_name, "status": s.status,
                     "gate_decision": s.gate_decision} for s in run.stages],
        "failure_reason": run.failure_reason,
    }


@mcp.tool(name="autopilot_resume")
def autopilot_resume_tool(run_id: str) -> dict:
    """Resume a paused autopilot run from the blocked stage.

    Only works for runs with status=paused_for_approval or paused_for_revision.
    """
    run, artifact_reg = resume(run_id)
    # resume() has already validated the run is in a paused state.
    # Paused states are sinks in the state machine (no outgoing transitions
    # via validate_transition), so we bypass the transition check here and
    # directly reset to "running" for orchestrator re-entry.
    run.status = "running"
    persist(run)

    registry = load_default_registry()
    orchestrator = LinearOrchestrator(
        registry=registry,
        runners={"spec_prep": run_spec_prep, "verify": run_verify, "ship": run_ship},
    )
    result = orchestrator.run_pipeline(run, artifact_registry=artifact_reg)
    return {
        "run_id": result.run_id, "status": result.status,
        "current_stage": result.current_stage,
        "stages": [{"stage": s.stage_name, "status": s.status} for s in result.stages],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
