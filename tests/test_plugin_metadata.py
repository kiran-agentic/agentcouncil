from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_plugin_manifest_points_to_shared_skills_and_mcp_config() -> None:
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())

    assert manifest["name"] == "agentcouncil"
    assert manifest["version"] == "0.4.0"
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


def test_start_server_script_supports_claude_and_codex_plugin_envs() -> None:
    script = (ROOT / "scripts" / "start-server.sh").read_text()

    assert "CODEX_PLUGIN_ROOT" in script
    assert "CLAUDE_PLUGIN_ROOT" in script
    assert "CODEX_PLUGIN_DATA" in script
    assert "CLAUDE_PLUGIN_DATA" in script
