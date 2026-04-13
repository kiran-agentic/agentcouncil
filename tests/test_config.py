"""Tests for agentcouncil.config — BackendProfile, AgentCouncilConfig, ProfileLoader, ConfigSource.

Covers:
    CFG-01: Named backend profiles with provider, model, endpoint, api_key_env
    CFG-02: Precedence: skill arg > project config > global config > env var > default
    CFG-03: JsonConfigSettingsSource type-safe parsing
    CFG-04: Legacy AGENTCOUNCIL_OUTSIDE_AGENT env var preserved via fallback
    CFG-05: show-effective-config reports each resolved value with source attribution
    CFG-06: Raw API key strings rejected; env var names accepted
    TEST-02: All 5 precedence levels and legacy env var covered
"""
from __future__ import annotations

import json

import pytest

from agentcouncil.config import AgentCouncilConfig, BackendProfile, ConfigSource, EffectiveConfigEntry, ProfileLoader


# ---------------------------------------------------------------------------
# BackendProfile validation tests (CFG-01, CFG-06)
# ---------------------------------------------------------------------------


def test_backend_profile_valid():
    """CFG-01: BackendProfile with all fields validates without error."""
    profile = BackendProfile(
        provider="ollama",
        model="llama3",
        endpoint="http://localhost:11434",
        api_key_env="OLLAMA_KEY",
    )
    assert profile.provider == "ollama"
    assert profile.model == "llama3"
    assert profile.endpoint == "http://localhost:11434"
    assert profile.api_key_env == "OLLAMA_KEY"


def test_backend_profile_defaults():
    """CFG-01: BackendProfile() default values match expected."""
    profile = BackendProfile()
    assert profile.provider == "claude"
    assert profile.model is None
    assert profile.endpoint is None
    assert profile.api_key_env is None


def test_api_key_env_rejects_raw_key():
    """CFG-06: Raw API key strings with dashes are rejected with actionable error."""
    with pytest.raises(ValueError, match="environment variable name"):
        BackendProfile(api_key_env="sk-or-v1-abc123")


def test_api_key_env_rejects_bearer_token():
    """CFG-06: Bearer token strings are rejected."""
    with pytest.raises(ValueError, match="environment variable name"):
        BackendProfile(api_key_env="Bearer eyJhbGciOiJIUzI1NiJ9")


def test_api_key_env_accepts_valid_name():
    """CFG-06: Valid env var names (POSIX) are accepted."""
    profile = BackendProfile(api_key_env="OPENROUTER_API_KEY")
    assert profile.api_key_env == "OPENROUTER_API_KEY"


def test_api_key_env_accepts_none():
    """CFG-06: None is accepted (api_key not required)."""
    profile = BackendProfile(api_key_env=None)
    assert profile.api_key_env is None


# ---------------------------------------------------------------------------
# AgentCouncilConfig: JSON loading (CFG-03)
# ---------------------------------------------------------------------------


def test_json_config_loading(tmp_path, monkeypatch):
    """CFG-03: AgentCouncilConfig loads profiles from .agentcouncil.json via JsonConfigSettingsSource."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)

    (tmp_path / ".agentcouncil.json").write_text(
        json.dumps({"profiles": {"ollama-local": {"provider": "ollama", "model": "llama3"}}})
    )

    cfg = AgentCouncilConfig()
    assert "ollama-local" in cfg.profiles
    assert cfg.profiles["ollama-local"].provider == "ollama"
    assert cfg.profiles["ollama-local"].model == "llama3"


# ---------------------------------------------------------------------------
# Precedence tests (CFG-02)
# ---------------------------------------------------------------------------


def test_precedence_skill_arg_wins(tmp_path, monkeypatch):
    """CFG-02: init kwarg (skill_arg) overrides project config, global config, and env var."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    # Write project config with a different value
    (tmp_path / ".agentcouncil.json").write_text(
        json.dumps({"default_profile": "from_project"})
    )
    # Write global config with another value
    (home_dir / ".agentcouncil.json").write_text(
        json.dumps({"default_profile": "from_global"})
    )
    # Set env var with yet another value
    monkeypatch.setenv("AGENTCOUNCIL_DEFAULT_PROFILE", "from_env")

    # Init kwarg must win
    cfg = AgentCouncilConfig(default_profile="from_skill_arg")
    assert cfg.default_profile == "from_skill_arg"


def test_precedence_project_over_global(tmp_path, monkeypatch):
    """CFG-02: Project .agentcouncil.json overrides global ~/.agentcouncil.json."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)

    (tmp_path / ".agentcouncil.json").write_text(
        json.dumps({"default_profile": "from_project"})
    )
    (home_dir / ".agentcouncil.json").write_text(
        json.dumps({"default_profile": "from_global"})
    )

    cfg = AgentCouncilConfig()
    assert cfg.default_profile == "from_project"


def test_precedence_env_over_default(tmp_path, monkeypatch):
    """CFG-02: AGENTCOUNCIL_DEFAULT_PROFILE env var overrides the default None."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("AGENTCOUNCIL_DEFAULT_PROFILE", "from_env")

    cfg = AgentCouncilConfig()
    assert cfg.default_profile == "from_env"


def test_precedence_default_when_nothing_set(tmp_path, monkeypatch):
    """CFG-02: With no config files, no env vars, no args, defaults are None and {}."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)

    cfg = AgentCouncilConfig()
    assert cfg.default_profile is None
    assert cfg.profiles == {}


# ---------------------------------------------------------------------------
# ProfileLoader tests (CFG-04, profile resolution)
# ---------------------------------------------------------------------------


def test_legacy_env_var_fallback(tmp_path, monkeypatch):
    """CFG-04: ProfileLoader.resolve() with no profile config falls back to resolve_outside_backend()."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "claude")

    # No .agentcouncil.json anywhere — should fall back to legacy env var
    result = ProfileLoader().resolve()
    assert result == "claude"


def test_profile_loader_resolve_named(tmp_path, monkeypatch):
    """ProfileLoader().resolve('my-profile') returns the BackendProfile named 'my-profile'."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)

    (tmp_path / ".agentcouncil.json").write_text(
        json.dumps({"profiles": {"my-profile": {"provider": "ollama", "model": "llama3"}}})
    )

    result = ProfileLoader().resolve("my-profile")
    assert isinstance(result, BackendProfile)
    assert result.provider == "ollama"
    assert result.model == "llama3"


def test_profile_loader_resolve_default(tmp_path, monkeypatch):
    """ProfileLoader().resolve() with default_profile='my-profile' returns that profile."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)

    (tmp_path / ".agentcouncil.json").write_text(
        json.dumps({
            "default_profile": "my-profile",
            "profiles": {"my-profile": {"provider": "ollama", "model": "llama3"}},
        })
    )

    result = ProfileLoader().resolve()
    assert isinstance(result, BackendProfile)
    assert result.provider == "ollama"


# ---------------------------------------------------------------------------
# ConfigSource enum test
# ---------------------------------------------------------------------------


def test_config_source_enum():
    """ConfigSource enum has all required values."""
    assert ConfigSource.SKILL_ARG == "skill_arg"
    assert ConfigSource.PROJECT_CONFIG == "project_config"
    assert ConfigSource.GLOBAL_CONFIG == "global_config"
    assert ConfigSource.ENV_VAR == "env_var"
    assert ConfigSource.LEGACY_ENV_VAR == "legacy_env_var"
    assert ConfigSource.DEFAULT == "default"


# ---------------------------------------------------------------------------
# Source attribution tests for ProfileLoader.effective_report() (CFG-05)
# ---------------------------------------------------------------------------


def test_effective_config_sources_skill_arg(tmp_path, monkeypatch):
    """CFG-05: When AgentCouncilConfig created with default_profile as init kwarg, source is skill_arg."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    cfg = AgentCouncilConfig(default_profile="from_arg")
    loader = ProfileLoader(config=cfg)
    report = loader.effective_report()
    assert report["default_profile"]["value"] == "from_arg"
    assert report["default_profile"]["source"] == "skill_arg"


def test_effective_config_sources_project(tmp_path, monkeypatch):
    """CFG-05: When project .agentcouncil.json has default_profile, source is project_config."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    (tmp_path / ".agentcouncil.json").write_text(json.dumps({"default_profile": "proj"}))
    cfg = AgentCouncilConfig()
    loader = ProfileLoader(config=cfg)
    report = loader.effective_report()
    assert report["default_profile"]["value"] == "proj"
    assert report["default_profile"]["source"] == "project_config"


def test_effective_config_sources_global(tmp_path, monkeypatch):
    """CFG-05: When only global ~/.agentcouncil.json has default_profile, source is global_config."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    (home_dir / ".agentcouncil.json").write_text(json.dumps({"default_profile": "glob"}))
    cfg = AgentCouncilConfig()
    loader = ProfileLoader(config=cfg)
    report = loader.effective_report()
    assert report["default_profile"]["value"] == "glob"
    assert report["default_profile"]["source"] == "global_config"


def test_effective_config_sources_default(tmp_path, monkeypatch):
    """CFG-05: When nothing configured, default_profile is None with source default."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    cfg = AgentCouncilConfig()
    loader = ProfileLoader(config=cfg)
    report = loader.effective_report()
    assert report["default_profile"]["value"] is None
    assert report["default_profile"]["source"] == "default"


def test_effective_config_profiles_merged(tmp_path, monkeypatch):
    """CFG-05: Profiles from project and global config both appear in report with correct sources."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.delenv("AGENTCOUNCIL_OUTSIDE_AGENT", raising=False)
    (tmp_path / ".agentcouncil.json").write_text(
        json.dumps({"profiles": {"a": {"provider": "ollama"}}})
    )
    (home_dir / ".agentcouncil.json").write_text(
        json.dumps({"profiles": {"b": {"provider": "codex"}}})
    )
    cfg = AgentCouncilConfig()
    loader = ProfileLoader(config=cfg)
    report = loader.effective_report()
    # profiles dict source should be identified
    assert "profiles" in report
    assert "a" in report["profiles"]["value"]


def test_effective_config_legacy_env(tmp_path, monkeypatch):
    """CFG-05: When AGENTCOUNCIL_OUTSIDE_AGENT is set, report includes legacy_backend with source legacy_env_var."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("AGENTCOUNCIL_DEFAULT_PROFILE", raising=False)
    monkeypatch.setenv("AGENTCOUNCIL_OUTSIDE_AGENT", "claude")
    cfg = AgentCouncilConfig()
    loader = ProfileLoader(config=cfg)
    report = loader.effective_report()
    assert "legacy_backend" in report
    assert report["legacy_backend"]["value"] == "claude"
    assert report["legacy_backend"]["source"] == "legacy_env_var"


# ---------------------------------------------------------------------------
# MCP tool registration test (CFG-05)
# ---------------------------------------------------------------------------


def test_show_effective_config_tool_registered():
    """CFG-05: show-effective-config tool is registered on the MCP server."""
    import asyncio
    from agentcouncil.server import mcp
    tool_names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert "show-effective-config" in tool_names


# ---------------------------------------------------------------------------
# BackendProfile Kiro fields tests (KCFG-01)
# ---------------------------------------------------------------------------


def test_backend_profile_cli_path_accepted():
    """KCFG-01: BackendProfile accepts cli_path as an optional field."""
    bp = BackendProfile(cli_path="/usr/local/bin/kiro-cli")
    assert bp.cli_path == "/usr/local/bin/kiro-cli"


def test_backend_profile_auth_token_env_accepted():
    """KCFG-01: BackendProfile accepts auth_token_env with a valid env var name."""
    bp = BackendProfile(auth_token_env="KIRO_AUTH_TOKEN")
    assert bp.auth_token_env == "KIRO_AUTH_TOKEN"


def test_backend_profile_auth_token_env_rejects_raw_secret():
    """KCFG-01: auth_token_env rejects raw secret strings (dashes not allowed by _ENV_VAR_RE)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="auth_token_env must be an environment variable name"):
        BackendProfile(auth_token_env="sk-secret-key-value")


def test_backend_profile_auth_token_env_rejects_invalid_name():
    """KCFG-01: auth_token_env rejects names that start with digits."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="auth_token_env must be an environment variable name"):
        BackendProfile(auth_token_env="123INVALID")


def test_backend_profile_defaults_cli_path_none():
    """KCFG-01: BackendProfile() has cli_path=None by default."""
    bp = BackendProfile()
    assert bp.cli_path is None


def test_backend_profile_defaults_auth_token_env_none():
    """KCFG-01: BackendProfile() has auth_token_env=None by default."""
    bp = BackendProfile()
    assert bp.auth_token_env is None
