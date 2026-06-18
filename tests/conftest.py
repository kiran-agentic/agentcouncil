"""Shared fixtures for agentcouncil tests."""
import pytest

from agentcouncil.config import set_project_dir

# Every environment variable that influences host detection (agentcouncil.host).
# Cleared before each test so the suite resolves the historical "claude" default
# regardless of the host it runs under (e.g. a Codex/Cursor-host contributor or CI
# runner that injects CODEX_PLUGIN_ROOT / CLAUDECODE into the environment).
_HOST_ENV_VARS = (
    "AGENTCOUNCIL_HOST",
    "AGENTCOUNCIL_OUTSIDE_AGENT",
    "AGENTCOUNCIL_LEAD_AGENT",
    "CODEX_PLUGIN_ROOT",
    "CODEX_HOME",
    "CODEX_SANDBOX",
    "CODEX_PLUGIN_DATA",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_PLUGIN_DATA",
)


@pytest.fixture(autouse=True)
def _neutralize_host_env(monkeypatch):
    """Clear host-detection env vars so tests start from a known host-neutral baseline.

    Tests that want a specific host set AGENTCOUNCIL_HOST themselves after this runs.
    """
    for var in _HOST_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_project_dir():
    """Reset the global project_dir between tests to prevent cross-test pollution."""
    yield
    set_project_dir(None)


@pytest.fixture(autouse=True)
def _reset_resolved_workspace():
    """Reset the server's cached workspace between tests."""
    import agentcouncil.server as srv
    old = srv._resolved_workspace
    yield
    srv._resolved_workspace = old
