"""Shared fixtures for agentcouncil tests."""
import pytest

from agentcouncil.config import set_project_dir


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
