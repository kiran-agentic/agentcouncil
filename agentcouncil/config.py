"""agentcouncil.config — Named backend profiles with 5-level precedence resolution.

Provides:
    BackendProfile      — Pydantic model for a single backend profile entry
    AgentCouncilConfig  — pydantic-settings BaseSettings with layered JSON config sources
    ProfileLoader       — Resolves a named profile from the 5-level precedence stack
    ConfigSource        — Enum of all config source levels
    EffectiveConfigEntry — Model for a single field's resolved value + source label
"""
from __future__ import annotations

import os
import re
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings, JsonConfigSettingsSource

__all__ = ["BackendProfile", "AgentCouncilConfig", "ProfileLoader", "ConfigSource", "EffectiveConfigEntry"]

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# ConfigSource enum
# ---------------------------------------------------------------------------


class ConfigSource(str, Enum):
    """Source levels in the 5-level config precedence stack."""

    SKILL_ARG = "skill_arg"
    PROJECT_CONFIG = "project_config"
    GLOBAL_CONFIG = "global_config"
    ENV_VAR = "env_var"
    LEGACY_ENV_VAR = "legacy_env_var"
    DEFAULT = "default"


# ---------------------------------------------------------------------------
# EffectiveConfigEntry — per-field source attribution (CFG-05)
# ---------------------------------------------------------------------------


class EffectiveConfigEntry(BaseModel):
    """A single field's resolved value alongside the source that provided it."""

    value: Any
    source: str


# ---------------------------------------------------------------------------
# BackendProfile model (CFG-01, CFG-06)
# ---------------------------------------------------------------------------


class BackendProfile(BaseModel):
    """A single named backend profile from .agentcouncil.json.

    Fields:
        provider    — e.g. "codex", "ollama", "openrouter", "bedrock"
        model       — optional model override (e.g. "llama3", "o4-mini")
        endpoint    — optional base URL for HTTP-based providers
        api_key_env — POSIX env var NAME that holds the API key, never the raw secret
    """

    provider: str = "claude"
    model: str | None = None
    endpoint: str | None = None
    api_key_env: str | None = None  # env var NAME, never a raw key
    cli_path: str | None = None          # Binary override (e.g. /usr/local/bin/kiro-cli)
    auth_token_env: str | None = None    # Future KIRO_AUTH_TOKEN env var name

    @model_validator(mode="after")
    def reject_raw_api_keys(self) -> BackendProfile:
        """CFG-06: Reject raw API key strings in api_key_env and auth_token_env."""
        if self.api_key_env is not None:
            if not _ENV_VAR_RE.match(self.api_key_env):
                raise ValueError(
                    f"api_key_env must be an environment variable name "
                    f"(e.g. OPENROUTER_API_KEY), not a raw secret. "
                    f"Got: {self.api_key_env!r}"
                )
        if self.auth_token_env is not None:
            if not _ENV_VAR_RE.match(self.auth_token_env):
                raise ValueError(
                    f"auth_token_env must be an environment variable name "
                    f"(e.g. KIRO_AUTH_TOKEN), not a raw secret. "
                    f"Got: {self.auth_token_env!r}"
                )
        return self


# ---------------------------------------------------------------------------
# AgentCouncilConfig — BaseSettings with layered JSON sources (CFG-02, CFG-03)
# ---------------------------------------------------------------------------


class AgentCouncilConfig(BaseSettings):
    """AgentCouncil configuration loaded from multiple layered sources.

    Source precedence (highest to lowest):
        1. init kwargs (skill_arg)
        2. AGENTCOUNCIL_* env vars
        3. .agentcouncil.json in cwd (project config)
        4. ~/.agentcouncil.json (global config)
        5. pydantic field defaults

    Notes:
        - extra="ignore" prevents AGENTCOUNCIL_OUTSIDE_AGENT from causing
          ValidationError (Pitfall 5 from research). Legacy behavior is
          preserved via ProfileLoader fallback to resolve_outside_backend().
        - Path.cwd() and Path.home() are called at instantiation time
          (inside settings_customise_sources), not at class definition time,
          so monkeypatch.chdir() works correctly in tests (Pitfall 3).
    """

    profiles: dict[str, BackendProfile] = {}
    default_profile: str | None = None

    model_config = {"env_prefix": "AGENTCOUNCIL_", "extra": "ignore"}

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):  # type: ignore[override]
        """Return source tuple in precedence order (highest first).

        Called at instantiation time by pydantic-settings.
        """
        project_cfg = Path.cwd() / ".agentcouncil.json"
        global_cfg = Path.home() / ".agentcouncil.json"
        return (
            kwargs["init_settings"],  # skill_arg (highest priority)
            kwargs["env_settings"],  # AGENTCOUNCIL_* env vars
            JsonConfigSettingsSource(settings_cls, json_file=project_cfg),  # project
            JsonConfigSettingsSource(settings_cls, json_file=global_cfg),  # global
        )


# ---------------------------------------------------------------------------
# ProfileLoader — 5-level precedence resolution (CFG-02, CFG-04)
# ---------------------------------------------------------------------------


class ProfileLoader:
    """Resolves a named backend profile using the precedence stack.

    Levels (highest to lowest):
        1. skill_arg (profile_name argument to resolve())
        2. env var / config default_profile (AGENTCOUNCIL_DEFAULT_PROFILE via AgentCouncilConfig,
           which loads env > project config > global config > pydantic default)
        3. built-in provider name passthrough (profile_name in VALID_BACKENDS)
        4. legacy env var (AGENTCOUNCIL_OUTSIDE_AGENT via resolve_outside_backend())
        5. default ("claude" from resolve_outside_backend())
    """

    def __init__(self, config: AgentCouncilConfig | None = None) -> None:
        self._config: AgentCouncilConfig = config if config is not None else AgentCouncilConfig()

    def resolve(
        self,
        profile_name: str | None = None,
        skill_backend: str | None = None,
    ) -> BackendProfile | str:
        """Resolve to a BackendProfile or a legacy backend string.

        Returns:
            BackendProfile if a named profile is found.
            str ("codex" or "claude") if falling back to legacy behavior.

        Precedence:
            1. profile_name arg → look up in profiles dict
            2. config.default_profile → look up in profiles dict
            3. Built-in provider name passthrough — if profile_name is a
               recognized backend string ("codex", "claude"), it is passed
               through to resolve_outside_backend() so the correct provider
               is dispatched without requiring a named profile.
            4. resolve_outside_backend(skill_backend) — legacy fallback (CFG-04)
        """
        # Level 1: explicit profile_name argument
        if profile_name is not None and profile_name in self._config.profiles:
            return self._config.profiles[profile_name]

        # Level 2: default_profile from config (project > global > env > pydantic default)
        if (
            self._config.default_profile is not None
            and self._config.default_profile in self._config.profiles
        ):
            return self._config.profiles[self._config.default_profile]

        # Level 3+: legacy fallback — preserves AGENTCOUNCIL_OUTSIDE_AGENT and "claude" default
        # Pass profile_name as skill_backend when it's a recognized backend string,
        # so built-in provider names ("codex", "claude") resolve correctly instead
        # of silently falling through to the default.
        from agentcouncil.adapters import VALID_BACKENDS, resolve_outside_backend

        effective_backend = skill_backend
        if effective_backend is None and profile_name in VALID_BACKENDS:
            effective_backend = profile_name
        return resolve_outside_backend(effective_backend)

    def effective_report(self) -> dict[str, dict[str, Any]]:
        """Return per-field source attribution for every config field.

        For each field in AgentCouncilConfig, reports which source level provided
        the winning value. Sources are checked in precedence order:
            skill_arg > env_var > project_config > global_config > default

        Also reports legacy_backend if AGENTCOUNCIL_OUTSIDE_AGENT is set.

        Returns:
            Dict mapping field names to {"value": <value>, "source": <source_label>}.
            source_label is one of: skill_arg, project_config, global_config,
            env_var, legacy_env_var, default.
        """
        project_path = Path.cwd() / ".agentcouncil.json"
        global_path = Path.home() / ".agentcouncil.json"

        # Call each source independently to get its raw dict
        project_src = JsonConfigSettingsSource(AgentCouncilConfig, json_file=project_path)
        global_src = JsonConfigSettingsSource(AgentCouncilConfig, json_file=global_path)

        project_dict: dict[str, Any] = project_src() or {}
        global_dict: dict[str, Any] = global_src() or {}

        # Build env var dict manually (AGENTCOUNCIL_* prefix)
        env_dict: dict[str, Any] = {}
        env_val = os.environ.get("AGENTCOUNCIL_DEFAULT_PROFILE")
        if env_val is not None:
            env_dict["default_profile"] = env_val
        env_profiles = os.environ.get("AGENTCOUNCIL_PROFILES")
        if env_profiles is not None:
            env_dict["profiles"] = env_profiles

        # Determine if any init kwargs were passed by comparing the merged config
        # against what project/global/env sources would provide alone.
        # We re-create a config from non-init sources only to detect init overrides.
        cfg_without_init = AgentCouncilConfig()
        merged = self._config

        # Fields to report on
        fields: dict[str, Any] = {"default_profile": None, "profiles": {}}

        # Sources in precedence order (highest to lowest) for field sweep.
        # Note: skill_arg is checked separately via comparison below.
        source_order = [
            (ConfigSource.ENV_VAR, env_dict),
            (ConfigSource.PROJECT_CONFIG, project_dict),
            (ConfigSource.GLOBAL_CONFIG, global_dict),
        ]

        report: dict[str, dict[str, Any]] = {}

        for field_name, default_val in fields.items():
            actual_value = getattr(merged, field_name)

            # Check if the value came from init kwargs (skill_arg):
            # If the merged config differs from a config built without init kwargs,
            # and the difference is not explained by env/project/global sources,
            # then it must have come from init kwargs.
            non_init_value = getattr(cfg_without_init, field_name)
            if actual_value != non_init_value:
                # merged differs from non-init → init kwargs (skill_arg) provided it
                report[field_name] = {"value": actual_value, "source": ConfigSource.SKILL_ARG.value}
                continue

            # Walk sources in precedence order to find the winning one
            found_source = ConfigSource.DEFAULT.value
            for src_label, src_dict in source_order:
                if field_name in src_dict and src_dict[field_name] is not None:
                    found_source = src_label.value
                    break

            report[field_name] = {"value": actual_value, "source": found_source}

        # Report legacy AGENTCOUNCIL_OUTSIDE_AGENT env var if set
        legacy = os.environ.get("AGENTCOUNCIL_OUTSIDE_AGENT")
        if legacy is not None:
            report["legacy_backend"] = {
                "value": legacy,
                "source": ConfigSource.LEGACY_ENV_VAR.value,
            }

        return report
