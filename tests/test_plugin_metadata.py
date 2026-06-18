from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_plugin_manifest_points_to_shared_skills_and_mcp_config() -> None:
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["name"] == "agentcouncil"
    assert manifest["version"] == "0.6.1"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert (ROOT / "skills").is_dir()
    assert (ROOT / ".mcp.json").is_file()


def test_codex_mcp_config_starts_agentcouncil_server_from_plugin_root() -> None:
    config = json.loads((ROOT / ".mcp.json").read_text())
    server = config["mcpServers"]["agentcouncil"]

    assert server["command"] == "./scripts/start-server.sh"
    assert server["args"] == []
    assert server["cwd"] == "."


def test_cursor_plugin_manifest_launches_server_with_relative_command() -> None:
    """Cursor installs from the repo URL via .cursor-plugin/plugin.json. The MCP
    command must be RELATIVE (Cursor resolves it from the plugin root and sets no
    CLAUDE_PLUGIN_ROOT), and must mark the host so the default backend is Cursor."""
    manifest = json.loads((ROOT / ".cursor-plugin" / "plugin.json").read_text())

    assert manifest["name"] == "agentcouncil"
    assert manifest["version"] == "0.6.1"
    assert manifest["skills"] == "./skills/"

    server = manifest["mcpServers"]["agentcouncil"]
    assert server["command"] == "./scripts/start-server.sh"
    assert "${CLAUDE_PLUGIN_ROOT}" not in server["command"]
    assert server["env"]["AGENTCOUNCIL_HOST"] == "cursor"


def test_start_server_script_supports_host_plugin_envs() -> None:
    script = (ROOT / "scripts" / "start-server.sh").read_text()

    for marker in (
        "CURSOR_PLUGIN_ROOT",
        "CODEX_PLUGIN_ROOT",
        "CLAUDE_PLUGIN_ROOT",
        "CURSOR_PLUGIN_DATA",
        "CODEX_PLUGIN_DATA",
        "CLAUDE_PLUGIN_DATA",
    ):
        assert marker in script
