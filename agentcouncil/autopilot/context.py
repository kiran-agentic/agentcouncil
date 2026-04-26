"""Autopilot review context packs.

Builds a small, sanitized per-run context artifact that lets review gates avoid
rediscovering the same repository facts on every pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agentcouncil.autopilot.run import PROJECT_RUNS_REL, checkpoint_run, load_run

RefreshPolicy = Literal["auto", "force", "never"]

CONTEXT_CACHE_DIR = Path.home() / ".agentcouncil" / "context"
MAX_READ_BYTES = 16_384
MANIFEST_NAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "tsconfig.json",
    "vite.config.ts",
    "vitest.config.ts",
    "jest.config.js",
    "jest.config.ts",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Makefile",
}
SECRET_FILE_NAMES = {".mcp.json", ".env", ".env.local", ".envrc"}
SKIP_DIRS = {
    ".git",
    ".claude",
    ".codex",
    ".serena",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".expo",
}


class ContextUnknown(BaseModel):
    kind: str
    severity: Literal["low", "medium", "high"] = "medium"
    message: str
    suggested_probe: str


class ReviewContextPack(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    spec_id: str
    project_hash: str
    stage: str
    created_at: float
    updated_at: float
    freshness: Literal["created", "refreshed", "reused"] = "created"
    repo_fingerprint: str
    target_files: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    manifest_files: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    stable_facts: list[str] = Field(default_factory=list)
    unknowns: list[ContextUnknown] = Field(default_factory=list)
    file_hashes: dict[str, str] = Field(default_factory=dict)
    context_ref: str | None = None

    def to_review_context(self) -> str:
        parts = [
            f"Run: {self.run_id}",
            f"Stage: {self.stage}",
            f"Freshness: {self.freshness}",
        ]
        if self.target_files:
            parts.append("Target files:\n" + "\n".join(f"- {p}" for p in self.target_files[:40]))
        if self.changed_files:
            parts.append("Changed files:\n" + "\n".join(f"- {p}" for p in self.changed_files[:40]))
        if self.test_commands:
            parts.append("Test commands:\n" + "\n".join(f"- {c}" for c in self.test_commands[:12]))
        if self.stable_facts:
            parts.append("Known project facts:\n" + "\n".join(f"- {f}" for f in self.stable_facts[:20]))
        if self.unknowns:
            parts.append(
                "Unknowns:\n"
                + "\n".join(f"- {u.kind}: {u.message}" for u in self.unknowns[:10])
            )
        return "\n\n".join(parts)


@dataclass(frozen=True)
class ContextPackResult:
    context_ref: str
    summary: str
    freshness: str
    included_files: list[str]
    unknowns: list[dict]

    def model_dump(self) -> dict:
        return {
            "context_ref": self.context_ref,
            "summary": self.summary,
            "freshness": self.freshness,
            "included_files": self.included_files,
            "unknowns": self.unknowns,
        }


_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "[REDACTED_GOOGLE_API_KEY]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"arn:aws:[^\s\"']+"), "[REDACTED_AWS_ARN]"),
    (re.compile(r"https?://[^\s\"']+[?&](?:X-Amz-Signature|signature|token)=[^\s\"']+"), "[REDACTED_SIGNED_URL]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)(api[_-]?key|secret|token|password)(['\"\s:=]+)([A-Za-z0-9_\-/.+=]{8,})"), r"\1\2[REDACTED_SECRET]"),
]


def sanitize_text(value: str) -> str:
    text = value
    home = str(Path.home())
    if home:
        text = text.replace(home, "~")
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def compute_project_hash(workspace_path: str | Path) -> str:
    workspace = Path(workspace_path).expanduser().resolve()

    def _git(args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    top = _git(["rev-parse", "--show-toplevel"])
    remote = _git(["config", "--get", "remote.origin.url"])
    if remote:
        identity = f"git-remote:{_normalize_remote(remote)}"
    elif top:
        commit = _git(["rev-parse", "HEAD"]) or "no-head"
        identity = f"git-local:{Path(top).name}:{commit}"
    else:
        identity = f"path:{sanitize_text(str(workspace))}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _normalize_remote(remote: str) -> str:
    value = remote.strip().lower()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@"):
        value = value.replace(":", "/", 1)
    return value


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _safe_relative(path: Path, root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    if any(part in SECRET_FILE_NAMES for part in rel.parts):
        return None
    return rel.as_posix()


def _is_secret_rel(rel: str) -> bool:
    return any(part in SECRET_FILE_NAMES for part in Path(rel).parts)


def _iter_project_files(root: Path):
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            base = Path(dirpath)
            for filename in filenames:
                if filename in SECRET_FILE_NAMES:
                    continue
                yield base / filename
    except (OSError, PermissionError):
        return


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")[:MAX_READ_BYTES]
    except (OSError, UnicodeDecodeError):
        return ""


def _discover_manifests(root: Path) -> list[str]:
    found: list[str] = []
    for path in _iter_project_files(root):
        if path.name not in MANIFEST_NAMES:
            continue
        rel = _safe_relative(path, root)
        if rel is not None:
            found.append(rel)
        if len(found) >= 50:
            return sorted(set(found))
    return sorted(set(found))


def _discover_relevant_files(root: Path, target_files: list[str], changed_files: list[str]) -> list[str]:
    files = list(dict.fromkeys([*target_files, *changed_files]))
    if files:
        return [p for p in files if not _is_secret_rel(p)]
    suffixes = {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs"}
    for path in _iter_project_files(root):
        if path.suffix not in suffixes:
            continue
        rel = _safe_relative(path, root)
        if rel is not None:
            files.append(rel)
        if len(files) >= 80:
            return files
    return files


def _file_hashes(root: Path, files: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in files:
        if _is_secret_rel(rel):
            continue
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        text = sanitize_text(_read_text(path))
        hashes[rel] = _sha_text(text)
    return hashes


def _redaction_audit(root: Path, files: list[str]) -> list[str]:
    audit: list[str] = []
    for rel in files:
        if _is_secret_rel(rel):
            continue
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        raw = _read_text(path)
        redacted = sanitize_text(raw)
        if raw != redacted:
            audit.append(f"Redactions applied in {rel}: [REDACTED_SECRET]")
    return audit


def _extract_test_commands(root: Path) -> list[str]:
    commands: list[str] = []
    package_json = root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(_read_text(package_json))
            scripts = data.get("scripts", {})
            for name in ("test", "test:unit", "vitest", "jest"):
                if isinstance(scripts, dict) and name in scripts:
                    commands.append(str(scripts[name]))
        except (json.JSONDecodeError, TypeError):
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.exists() and "[tool.pytest" in _read_text(pyproject):
        commands.append("python3 -m pytest")
    makefile = root / "Makefile"
    if makefile.exists() and re.search(r"^test\s*:", _read_text(makefile), re.MULTILINE):
        commands.append("make test")
    return list(dict.fromkeys(commands))


def _repo_fingerprint(root: Path, files: list[str]) -> str:
    pieces = []
    for rel in files:
        path = root / rel
        if path.exists() and path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue
            pieces.append(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}")
    return _sha_text("\n".join(sorted(pieces)))


def _load_global_memory(project_hash: str) -> dict:
    path = CONTEXT_CACHE_DIR / f"{project_hash}.json"
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def record_successful_context_memory(context_ref: str) -> None:
    """Distill a successful per-run context pack into the global project cache."""
    try:
        pack = ReviewContextPack.model_validate_json(Path(context_ref).read_text())
    except (OSError, ValueError):
        return
    now = time.time()
    memory = _load_global_memory(pack.project_hash)
    stable_facts = list(dict.fromkeys([
        *[str(item) for item in memory.get("stable_facts", []) if isinstance(item, str)],
        *pack.stable_facts,
    ]))[:100]
    payload = {
        "schema_version": "1.0",
        "project_hash": pack.project_hash,
        "repo_fingerprint": pack.repo_fingerprint,
        "created_at": memory.get("created_at", now),
        "updated_at": now,
        "last_used_at": now,
        "stable_facts": stable_facts,
        "test_commands": list(dict.fromkeys([
            *[str(item) for item in memory.get("test_commands", []) if isinstance(item, str)],
            *pack.test_commands,
        ]))[:30],
        "manifest_files": pack.manifest_files[:100],
        "size": 0,
    }
    payload = _sanitize_payload(payload)
    payload["size"] = len(json.dumps(payload))
    try:
        CONTEXT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CONTEXT_CACHE_DIR / f"{pack.project_hash}.json").write_text(
            json.dumps(payload, indent=2) + "\n"
        )
    except OSError:
        return


def _cleanup_global_cache() -> None:
    try:
        CONTEXT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 30 * 24 * 60 * 60
        entries = sorted(CONTEXT_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for path in entries:
            try:
                data = json.loads(path.read_text())
                if float(data.get("last_used_at", path.stat().st_mtime)) < cutoff:
                    path.unlink()
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        entries = sorted(CONTEXT_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while sum(p.stat().st_size for p in entries if p.exists()) > 10 * 1024 * 1024 and entries:
            entries.pop(0).unlink(missing_ok=True)
    except OSError:
        return


def _context_path(workspace: Path, run_id: str) -> Path:
    return workspace / PROJECT_RUNS_REL / run_id / "context.json"


def _context_ref(run_id: str) -> str:
    return (PROJECT_RUNS_REL / run_id / "context.json").as_posix()


def _load_existing(path: Path) -> ReviewContextPack:
    return ReviewContextPack.model_validate_json(path.read_text())


def build_context_pack(
    *,
    run_id: str,
    workspace_path: str | Path,
    stage: str,
    changed_files: list[str] | None = None,
    artifact_refs: dict[str, str] | None = None,
    refresh_policy: RefreshPolicy = "auto",
) -> ContextPackResult:
    if refresh_policy not in {"auto", "force", "never"}:
        raise ValueError("refresh_policy must be one of: auto, force, never")

    run = load_run(run_id)
    workspace = Path(workspace_path).expanduser().resolve()
    path = _context_path(workspace, run_id)
    changed = changed_files or []

    if refresh_policy in {"auto", "never"} and path.exists():
        try:
            existing = _load_existing(path)
            if refresh_policy == "never":
                return _result(existing, "reused", _context_ref(run_id))
            manifest_files = _discover_manifests(workspace)
            watched = sorted(set([*existing.target_files, *existing.changed_files, *manifest_files]))
            fingerprint = _repo_fingerprint(workspace, watched)
            if fingerprint == existing.repo_fingerprint:
                return _result(existing, "reused", _context_ref(run_id))
        except (OSError, ValueError) as exc:
            if refresh_policy == "never":
                raise ValueError("corrupted context pack; refresh_policy='never' refuses regeneration") from exc
        except Exception as exc:
            if refresh_policy == "never":
                raise ValueError("corrupted context pack; refresh_policy='never' refuses regeneration") from exc

    _cleanup_global_cache()
    project_hash = compute_project_hash(workspace)
    global_memory = _load_global_memory(project_hash)
    target_files = [p for p in run.spec_target_files if not _is_secret_rel(p)]
    changed = [p for p in changed if not _is_secret_rel(p)]
    manifest_files = _discover_manifests(workspace)
    relevant_files = _discover_relevant_files(workspace, target_files, changed)
    watched_files = sorted(set([*target_files, *changed, *manifest_files]))
    file_hashes = _file_hashes(workspace, watched_files)
    test_commands = _extract_test_commands(workspace)
    stable_facts = [
        sanitize_text(str(item))
        for item in global_memory.get("stable_facts", [])
        if isinstance(item, str)
    ][:20]
    stable_facts.extend(_redaction_audit(workspace, watched_files))
    if manifest_files:
        stable_facts.append("Manifest-driven project detection: " + ", ".join(manifest_files[:8]))
    unknowns: list[ContextUnknown] = []
    if not test_commands:
        unknowns.append(ContextUnknown(
            kind="test_commands",
            severity="medium",
            message="No test command detected from manifests.",
            suggested_probe="Inspect project docs or CI workflow for test command.",
        ))
    if not target_files and not changed:
        unknowns.append(ContextUnknown(
            kind="target_files",
            severity="medium",
            message="No target or changed files supplied for focused review.",
            suggested_probe="Pass target_files during autopilot_prepare or changed_files to autopilot_context_pack.",
        ))

    now = time.time()
    pack = ReviewContextPack(
        run_id=run.run_id,
        spec_id=run.spec_id,
        project_hash=project_hash,
        stage=stage,
        created_at=now,
        updated_at=now,
        freshness="created" if not path.exists() else "refreshed",
        repo_fingerprint=_repo_fingerprint(workspace, watched_files),
        target_files=target_files,
        changed_files=changed,
        manifest_files=manifest_files,
        relevant_files=relevant_files,
        test_commands=test_commands,
        stable_facts=stable_facts,
        unknowns=unknowns,
        file_hashes=file_hashes,
        context_ref=(PROJECT_RUNS_REL / run_id / "context.json").as_posix(),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(pack.model_dump_json(indent=2))
    payload = _sanitize_payload(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    checkpoint_run(
        run_id,
        protocol_step=run.protocol_step,
        next_required_action=run.next_required_action,
        required_tool=run.required_tool,
        blocking_reason=run.blocking_reason,
        artifact_refs={**(artifact_refs or {}), "context_pack": _context_ref(run_id)},
        workspace_path=workspace,
    )
    return _result(pack, pack.freshness, _context_ref(run_id))


def _sanitize_payload(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if key in {"raw_logs", "transcript"}:
                continue
            clean[sanitize_text(str(key))] = _sanitize_payload(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def _result(pack: ReviewContextPack, freshness: str, context_ref: str | None = None) -> ContextPackResult:
    return ContextPackResult(
        context_ref=context_ref or pack.context_ref or "",
        summary=pack.to_review_context(),
        freshness=freshness,
        included_files=pack.relevant_files,
        unknowns=[u.model_dump() for u in pack.unknowns],
    )
