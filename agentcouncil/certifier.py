"""agentcouncil.certifier — Conformance certification for outside model backends.

Provides:
    CertificationResult   — Pydantic model with 4 boolean capability dimensions
    CertificationCache    — JSON file store for certification results
    ConformanceCertifier  — Scripted scenario runner for certifying a provider
    check_certification_gate  — Protocol gate enforcing tool-use requirement
    warn_stale_certification  — Prints stale-cert warning to stderr
    _get_agentcouncil_version — Returns current package version or "dev"

Design notes:
    - All certifications stored in a single certifications.json dict keyed by
      cache_key (avoids filename collision issues with model IDs containing "/")
    - Uncertified models are NOT blocked (pitfall 4 from RESEARCH: absence of
      evidence != evidence of absence)
    - Stale certs (agentcouncil_version mismatch) warn but do not block
    - Only review and challenge protocols require tool-use capability
"""
from __future__ import annotations

import importlib.metadata
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentcouncil.providers.base import OutsideProvider
from agentcouncil.runtime import OutsideRuntime, TokenBudgetExceeded
from agentcouncil.session import OutsideSession

__all__ = [
    "CertificationResult",
    "CertificationCache",
    "ConformanceCertifier",
    "check_certification_gate",
    "warn_stale_certification",
    "_get_agentcouncil_version",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".agentcouncil" / "certifications"

# Protocols that require function-calling capability
_GATED_PROTOCOLS = frozenset({"review", "challenge"})


# ---------------------------------------------------------------------------
# Version helper
# ---------------------------------------------------------------------------


def _get_agentcouncil_version() -> str:
    """Return the installed agentcouncil package version.

    Returns:
        Version string (e.g. "0.1.0") or "dev" if package metadata not found.
    """
    try:
        return importlib.metadata.version("agentcouncil")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


# ---------------------------------------------------------------------------
# CertificationResult model
# ---------------------------------------------------------------------------


class CertificationResult(BaseModel):
    """Evidence-based capability certification for an outside model backend.

    Fields:
        model_id              — Identifier for the certified model
        provider_version      — Provider SDK version used during certification
        agentcouncil_version  — agentcouncil package version used during certification
        certified_at          — ISO 8601 datetime string of certification
        tool_use              — Model can invoke function-calling tools
        multi_turn_coherence  — Model maintains context across conversation turns
        structured_output     — Model can produce valid JSON output on request
        budget_adherence      — Model completes within character budget limits
    """

    model_id: str
    provider_version: str = "unknown"
    agentcouncil_version: str
    certified_at: str
    tool_use: bool
    multi_turn_coherence: bool
    structured_output: bool
    budget_adherence: bool

    @property
    def cache_key(self) -> str:
        """Unique key for this certification: model_id::provider_version::agentcouncil_version."""
        return f"{self.model_id}::{self.provider_version}::{self.agentcouncil_version}"

    @property
    def is_prompt_only(self) -> bool:
        """True when the model does not support function-calling tools."""
        return not self.tool_use

    @property
    def supports_tools(self) -> bool:
        """True when the model supports function-calling tools."""
        return self.tool_use


# ---------------------------------------------------------------------------
# CertificationCache
# ---------------------------------------------------------------------------


class CertificationCache:
    """JSON file store for CertificationResult objects.

    All certifications are stored in a single ``certifications.json`` dict
    keyed by ``CertificationResult.cache_key``. This avoids filename collision
    when model IDs contain ``/`` or other special characters.

    Args:
        cache_dir — Directory to store certifications.json (default: ~/.agentcouncil/certifications)
    """

    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self._cache_dir = cache_dir
        self._cache_file = cache_dir / "certifications.json"

    def _load_all(self) -> dict[str, Any]:
        """Load the entire certifications.json file.

        Returns:
            Dict mapping cache_key -> CertificationResult dict. Empty dict if file absent.
        """
        if not self._cache_file.exists():
            return {}
        try:
            return json.loads(self._cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_all(self, data: dict[str, Any]) -> None:
        """Persist the certifications dict to disk."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(
        self,
        model_id: str,
        provider_version: str = "unknown",
        agentcouncil_version: str | None = None,
    ) -> CertificationResult | None:
        """Load a certification by exact key match.

        Args:
            model_id             — Model to look up
            provider_version     — Provider version (default "unknown")
            agentcouncil_version — agentcouncil version; uses current version if None

        Returns:
            CertificationResult if found, None otherwise.
        """
        if agentcouncil_version is None:
            agentcouncil_version = _get_agentcouncil_version()
        cache_key = f"{model_id}::{provider_version}::{agentcouncil_version}"
        data = self._load_all()
        entry = data.get(cache_key)
        if entry is None:
            return None
        return CertificationResult.model_validate(entry)

    def save(self, result: CertificationResult) -> None:
        """Persist a CertificationResult.

        Args:
            result — CertificationResult to store (keyed by result.cache_key)
        """
        data = self._load_all()
        data[result.cache_key] = result.model_dump()
        self._save_all(data)

    def load_by_model(self, model_id: str) -> CertificationResult | None:
        """Return any certification for this model_id regardless of version.

        Used by check_certification_gate where we want to enforce capability
        constraints even if the cert is for a different agentcouncil version.

        Args:
            model_id — Model identifier to look up

        Returns:
            Most recently saved CertificationResult for model, None if not found.
        """
        data = self._load_all()
        for entry in data.values():
            if entry.get("model_id") == model_id:
                return CertificationResult.model_validate(entry)
        return None


# ---------------------------------------------------------------------------
# ConformanceCertifier
# ---------------------------------------------------------------------------


class ConformanceCertifier:
    """Scripted scenario runner that certifies an OutsideProvider's capabilities.

    Runs 4 scenarios against the provider and records boolean pass/fail results
    in a CertificationResult.

    Args:
        provider   — Backend provider to certify
        model_id   — Identifier for the model being certified
        workspace  — Workspace directory for tool scenarios
    """

    def __init__(self, provider: OutsideProvider, model_id: str, workspace: str) -> None:
        self._provider = provider
        self._model_id = model_id
        self._workspace = workspace

    async def certify(
        self, cache: CertificationCache | None = None
    ) -> CertificationResult:
        """Run all certification scenarios and return a CertificationResult.

        If cache is provided and a matching certification exists (same model_id
        and current agentcouncil_version), return the cached result immediately
        without running any scenarios.

        Args:
            cache — Optional CertificationCache; when provided, checks for hits
                    before running and saves results after running.

        Returns:
            CertificationResult with pass/fail boolean for each scenario.
        """
        current_version = _get_agentcouncil_version()

        # Cache hit check
        if cache is not None:
            cached = cache.load(
                model_id=self._model_id,
                provider_version="unknown",
                agentcouncil_version=current_version,
            )
            if cached is not None:
                return cached

        # Run all 4 scenarios
        tool_use = await self._test_tool_use()
        multi_turn_coherence = await self._test_multi_turn_coherence()
        structured_output = await self._test_structured_output()
        budget_adherence = await self._test_budget_adherence()

        result = CertificationResult(
            model_id=self._model_id,
            provider_version="unknown",
            agentcouncil_version=current_version,
            certified_at=datetime.utcnow().isoformat(),
            tool_use=tool_use,
            multi_turn_coherence=multi_turn_coherence,
            structured_output=structured_output,
            budget_adherence=budget_adherence,
        )

        if cache is not None:
            cache.save(result)

        return result

    async def _test_tool_use(self) -> bool:
        """Test whether the provider can use function-calling tools.

        Creates an OutsideRuntime + OutsideSession, sends a prompt asking
        the model to use list_files. Detects tool use by counting provider
        calls via a wrapper (provider-agnostic — works with any provider,
        not just StubProvider).

        Returns:
            True if at least one tool call was made, False otherwise.
        """
        try:
            call_count = 0
            original_chat_complete = self._provider.chat_complete

            async def counting_chat_complete(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return await original_chat_complete(*args, **kwargs)

            self._provider.chat_complete = counting_chat_complete  # type: ignore[assignment]
            try:
                runtime = OutsideRuntime(self._provider, self._workspace)
                session = OutsideSession(self._provider, runtime)
                await session.open()
                await session.call("List the files using the list_files tool.")
                await session.close()
                # Tool use detected if provider was called more than once
                # (first call returns tool_calls, second call after tool results)
                return call_count > 1
            finally:
                self._provider.chat_complete = original_chat_complete  # type: ignore[assignment]
        except Exception:
            return False

    async def _test_multi_turn_coherence(self) -> bool:
        """Test whether the provider maintains context across conversation turns.

        Turn 1: Asks model to remember a token (ALPHA-42).
        Turn 2: Asks model to repeat the token.
        Passes if "ALPHA-42" appears in the turn-2 response.

        Returns:
            True if token is retained across turns, False otherwise.
        """
        try:
            runtime = OutsideRuntime(self._provider, self._workspace)
            session = OutsideSession(self._provider, runtime)
            await session.open()
            await session.call("Remember this token: ALPHA-42")
            response = await session.call("Repeat the token I told you.")
            await session.close()
            return "ALPHA-42" in response
        except Exception:
            return False

    async def _test_structured_output(self) -> bool:
        """Test whether the provider can produce valid JSON output.

        Asks the model to return a JSON object. Passes if json.loads()
        succeeds on any JSON-like substring of the response.

        Returns:
            True if a valid JSON object is found in the response, False otherwise.
        """
        try:
            runtime = OutsideRuntime(self._provider, self._workspace)
            session = OutsideSession(self._provider, runtime)
            await session.open()
            response = await session.call(
                'Return a JSON object with key "status" and value "ok".'
            )
            await session.close()
            # Try to parse the response — may contain surrounding text
            json.loads(response)
            return True
        except json.JSONDecodeError:
            # Try to extract JSON from response
            try:
                start = response.index("{")
                end = response.rindex("}") + 1
                json.loads(response[start:end])
                return True
            except (ValueError, json.JSONDecodeError):
                return False
        except Exception:
            return False

    async def _test_budget_adherence(self) -> bool:
        """Test whether the provider completes within character budget limits.

        Creates an OutsideRuntime with a modest char_budget and runs a single
        turn. Passes if no TokenBudgetExceeded is raised.

        Returns:
            True if turn completes within budget, False on TokenBudgetExceeded.
        """
        try:
            runtime = OutsideRuntime(
                self._provider,
                self._workspace,
                char_budget=50_000,
            )
            session = OutsideSession(self._provider, runtime)
            await session.open()
            await session.call("Hello, please respond briefly.")
            await session.close()
            return True
        except TokenBudgetExceeded:
            return False
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Stale certification warning
# ---------------------------------------------------------------------------


def warn_stale_certification(model_id: str, profile: str | None) -> None:
    """Print a stale-certification warning to stderr.

    Called when a loaded certification's agentcouncil_version does not match
    the current installed version. Provides an actionable re-certification command.

    Args:
        model_id — Model identifier whose certification is stale
        profile  — Named profile for re-certification (if available)
    """
    if profile:
        recertify_cmd = f'python -m agentcouncil.certifier --profile="{profile}"'
    else:
        recertify_cmd = f'python -m agentcouncil.certifier --model="{model_id}"'

    print(
        f"[agentcouncil] WARNING: Certification for '{model_id}' is stale "
        f"(agentcouncil version mismatch). Re-certify with:\n  {recertify_cmd}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Protocol gate
# ---------------------------------------------------------------------------


def check_certification_gate(
    protocol: str,
    model_id: str | None,
    profile: str | None,
    cache: CertificationCache | None = None,
) -> None:
    """Check protocol capability requirements against cached certification.

    Gate rules:
    - brainstorm / decide: no gate (text-only models allowed)
    - review / challenge: requires tool_use=True
    - Uncertified model: no block (absence of evidence != evidence of absence)
    - Stale cert: warn to stderr but do not block
    - cache=None: no check possible, passes through

    Args:
        protocol  — Deliberation protocol name (review, challenge, brainstorm, decide)
        model_id  — Model identifier to check certification for
        profile   — Named profile (passed to stale warning for actionable message)
        cache     — CertificationCache to look up certification; None skips gate

    Raises:
        ValueError: if protocol is review/challenge and model is certified as prompt-only
    """
    # Only gate review and challenge
    if protocol not in _GATED_PROTOCOLS:
        return

    # No cache → cannot check, pass through
    if cache is None:
        return

    # No model_id → cannot check
    if model_id is None:
        return

    # Look up any cert for this model (version-agnostic)
    cert = cache.load_by_model(model_id)
    if cert is None:
        # Uncertified — no block
        return

    # Check for stale certification (version mismatch)
    current_version = _get_agentcouncil_version()
    if cert.agentcouncil_version != current_version:
        warn_stale_certification(model_id=model_id, profile=profile)
        return

    # Block prompt-only models on review/challenge
    if cert.is_prompt_only:
        raise ValueError(
            f"Model '{model_id}' is certified as prompt-only (tool_use=False) and cannot "
            f"be used with the '{protocol}' protocol, which requires function-calling "
            f"capability. Use brainstorm or decide instead, or switch to a model that "
            f"supports tool use and re-run certification."
        )
