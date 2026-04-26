from __future__ import annotations

import json
import subprocess

import pytest

from agentcouncil.autopilot.run import AutopilotRun, StageCheckpoint, persist


def _make_run(run_id: str = "run-context", target_files: list[str] | None = None) -> AutopilotRun:
    import time

    return AutopilotRun(
        run_id=run_id,
        spec_id="speed-review",
        status="running",
        current_stage="spec_prep",
        tier=2,
        execution_mode="skill",
        spec_target_files=target_files or [],
        stages=[StageCheckpoint(stage_name="spec_prep", status="pending")],
        started_at=time.time(),
        updated_at=time.time(),
    )


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    import agentcouncil.autopilot.run as rmod

    monkeypatch.setattr(rmod, "RUN_DIR", tmp_path / "autopilot")
    yield tmp_path / "autopilot"


def test_project_hash_shared_by_git_worktree(tmp_path, monkeypatch):
    from agentcouncil.autopilot.context import compute_project_hash

    root = tmp_path / "repo"
    worktree = tmp_path / "repo-worktree"
    root.mkdir()
    worktree.mkdir()

    def fake_run(cmd, **kwargs):
        cwd = kwargs.get("cwd")
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            top = root if cwd == str(root) else worktree
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{top}\n", stderr="")
        if cmd[:3] == ["git", "config", "--get"]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="git@github.com:Example/Repo.git\n", stderr=""
            )
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert compute_project_hash(root) == compute_project_hash(worktree)


def test_context_pack_sanitizes_and_writes_per_run(run_dir, tmp_path, monkeypatch):
    from agentcouncil.autopilot.context import build_context_pack

    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}})
    )
    (workspace / ".mcp.json").write_text('{"headers":{"x-goog-api-key":"AIzaSySECRET"}}')
    fake_github_token = "ghp_" + "a" * 36
    (workspace / "src.ts").write_text(f"const token = '{fake_github_token}';\n")

    run = _make_run(target_files=["src.ts", ".mcp.json"])
    persist(run)

    pack = build_context_pack(
        run_id=run.run_id,
        workspace_path=workspace,
        stage="spec_prep",
        changed_files=["src.ts", ".mcp.json"],
        refresh_policy="force",
    )

    context_path = workspace / "docs/autopilot/runs/run-context/context.json"
    assert context_path.exists()
    payload = json.loads(context_path.read_text())
    payload_text = json.dumps(payload)
    assert payload["run_id"] == "run-context"
    assert ".mcp.json" not in payload["target_files"]
    assert ".mcp.json" not in payload["changed_files"]
    assert payload["test_commands"] == ["vitest run"]
    assert "[REDACTED" in payload_text
    assert "AIzaSySECRET" not in payload_text
    assert "ghp_" not in payload_text
    assert ".mcp.json" not in payload_text
    assert pack.context_ref == "docs/autopilot/runs/run-context/context.json"


def test_context_pack_preserves_pending_gate_guard(run_dir, tmp_path):
    from agentcouncil.autopilot.context import build_context_pack
    from agentcouncil.autopilot.run import checkpoint_run, load_run

    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}})
    )
    run = _make_run()
    persist(run)
    checkpoint_run(
        run.run_id,
        protocol_step="awaiting_spec_review",
        next_required_action="Run the spec review gate before planning.",
        required_tool="review_loop",
        workspace_path=workspace,
    )

    build_context_pack(
        run_id=run.run_id,
        workspace_path=workspace,
        stage="spec_prep",
        refresh_policy="force",
    )

    updated = load_run(run.run_id)
    assert updated.protocol_step == "awaiting_spec_review"
    assert updated.next_required_action == "Run the spec review gate before planning."
    assert updated.required_tool == "review_loop"


def test_context_pack_ignores_claude_worktree_manifests(run_dir, tmp_path):
    from agentcouncil.autopilot.context import build_context_pack

    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}})
    )
    hidden = workspace / ".claude" / "worktrees" / "agent-123"
    hidden.mkdir(parents=True)
    (hidden / "package.json").write_text(
        json.dumps({"scripts": {"test": "wrong hidden test"}})
    )
    run = _make_run()
    persist(run)

    build_context_pack(
        run_id=run.run_id,
        workspace_path=workspace,
        stage="spec_prep",
        refresh_policy="force",
    )

    payload = json.loads(
        (workspace / "docs/autopilot/runs/run-context/context.json").read_text()
    )
    assert payload["manifest_files"] == ["package.json"]
    assert ".claude" not in json.dumps(payload)


def test_context_pack_refresh_never_blocks_corrupted_pack(run_dir, tmp_path):
    from agentcouncil.autopilot.context import build_context_pack

    workspace = tmp_path / "project"
    state_dir = workspace / "docs/autopilot/runs/run-context"
    state_dir.mkdir(parents=True)
    (state_dir / "context.json").write_text("{not-json")
    run = _make_run()
    persist(run)

    with pytest.raises(ValueError, match="corrupted context pack"):
        build_context_pack(
            run_id=run.run_id,
            workspace_path=workspace,
            stage="plan",
            refresh_policy="never",
        )


def test_global_memory_updates_only_after_successful_checkpoint(run_dir, tmp_path, monkeypatch):
    import agentcouncil.autopilot.context as context_mod
    from agentcouncil.autopilot.context import build_context_pack
    from agentcouncil.autopilot.run import checkpoint_run

    cache_dir = tmp_path / "global-context"
    monkeypatch.setattr(context_mod, "CONTEXT_CACHE_DIR", cache_dir)
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "package.json").write_text('{"scripts":{"test":"vitest run"}}\n')

    run = _make_run()
    persist(run)
    pack = build_context_pack(
        run_id=run.run_id,
        workspace_path=workspace,
        stage="spec_prep",
        refresh_policy="force",
    )
    assert list(cache_dir.glob("*.json")) == []

    # Direct checkpoint_run does not write global memory; the MCP checkpoint tool
    # is responsible for promoting successful context into the global cache.
    checkpoint_run(
        run.run_id,
        protocol_step="awaiting_spec_review",
        artifact_refs={"context_pack": pack.context_ref},
        workspace_path=workspace,
    )
    assert list(cache_dir.glob("*.json")) == []


def test_autopilot_context_pack_tool_updates_artifact_refs(run_dir, tmp_path, monkeypatch):
    monkeypatch.setattr("agentcouncil.server._resolve_workspace_sync", lambda: str(tmp_path))
    from agentcouncil.server import autopilot_context_pack_tool, autopilot_status_tool

    run = _make_run()
    persist(run)

    result = autopilot_context_pack_tool(
        run_id=run.run_id,
        stage="spec_prep",
        changed_files=[],
        refresh_policy="force",
        workspace_path=str(tmp_path),
    )

    status = autopilot_status_tool(run.run_id)
    assert result["context_ref"] == "docs/autopilot/runs/run-context/context.json"
    assert status["artifact_refs"]["context_pack"] == result["context_ref"]
    assert status["context_pack"]["freshness"] in {"created", "refreshed", "reused"}


def test_successful_checkpoint_promotes_context_to_global_memory(run_dir, tmp_path, monkeypatch):
    import agentcouncil.autopilot.context as context_mod
    from agentcouncil.server import autopilot_checkpoint_tool, autopilot_context_pack_tool

    cache_dir = tmp_path / "global-context"
    monkeypatch.setattr(context_mod, "CONTEXT_CACHE_DIR", cache_dir)
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "package.json").write_text('{"scripts":{"test":"vitest run"}}\n')
    run = _make_run()
    persist(run)

    result = autopilot_context_pack_tool(
        run_id=run.run_id,
        stage="spec_prep",
        refresh_policy="force",
        workspace_path=str(workspace),
    )
    autopilot_checkpoint_tool(
        run_id=run.run_id,
        protocol_step="awaiting_spec_review",
        artifact_refs={"context_pack": result["context_ref"]},
        workspace_path=str(workspace),
    )
    assert list(cache_dir.glob("*.json")) == []

    autopilot_checkpoint_tool(
        run_id=run.run_id,
        protocol_step="spec_review_passed",
        stage="spec_prep",
        stage_status="advanced",
        gate_decision="pass",
        artifact_refs={"context_pack": result["context_ref"]},
        workspace_path=str(workspace),
    )
    assert len(list(cache_dir.glob("*.json"))) == 1
