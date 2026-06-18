#!/usr/bin/env python3
"""Generate Cursor slash commands from AgentCouncil skills.

Cursor custom commands live in ``.cursor/commands/<name>.md`` as PLAIN markdown
(no YAML frontmatter) and support the ``$ARGUMENTS`` placeholder, which captures
the text the user types after ``/<name>``. This keeps the single source of truth
in ``skills/<name>/SKILL.md`` (used by Claude Code and Codex) and derives the
Cursor commands from it, so the protocols never drift between platforms.

Transformation applied to each SKILL.md:
  * strip the Claude/Codex YAML frontmatter (Cursor commands are plain markdown);
  * prepend a short header (description + a note that the tools come from the
    ``agentcouncil`` MCP server);
  * preserve the body verbatim. ``$ARGUMENTS`` is substituted by Cursor with the
    text typed after the command. The ``mcp__agentcouncil__*`` references use Claude
    Code's tool-naming convention; Cursor exposes the same tools via the agentcouncil
    MCP server and its agent generally calls them by intent, but the literal prefix
    is not guaranteed to match Cursor's tool-addressing scheme (verify against a live
    Cursor session).

Run from the repo root::

    python scripts/generate-cursor-commands.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
COMMANDS_DIR = REPO_ROOT / ".cursor" / "commands"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split leading YAML frontmatter from the markdown body.

    Returns ``(meta, body)``. Only top-level ``key: value`` pairs are parsed —
    enough for the ``name``/``description``/``argument-hint`` fields the skills use.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, text[match.end():]


def render_command(name: str, meta: dict[str, str], body: str) -> str:
    """Compose the Cursor command markdown for one skill."""
    description = meta.get("description", f"Run the AgentCouncil {name} protocol.").strip()
    arg_hint = meta.get("argument-hint", "").strip()
    lines = [
        description,
        "",
        f"> Runs the AgentCouncil **{name}** protocol through the `agentcouncil` "
        f"MCP server. Configure it in `.cursor/mcp.json` (see `docs/CURSOR.md`); "
        f"the `mcp__agentcouncil__*` tools referenced below are exposed by that "
        f"server.",
    ]
    if arg_hint:
        lines.append(">")
        lines.append(f"> **Arguments:** {arg_hint}")
    lines.append("")
    lines.append("")
    return "\n".join(lines) + body.lstrip("\n")


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print(f"skills directory not found: {SKILLS_DIR}", file=sys.stderr)
        return 1
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        name = skill_md.parent.name
        meta, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        dest = COMMANDS_DIR / f"{name}.md"
        dest.write_text(render_command(name, meta, body), encoding="utf-8")
        generated.append(dest.relative_to(REPO_ROOT))
    for path in generated:
        print(f"generated {path}")
    print(
        f"\n{len(generated)} Cursor command(s) written to "
        f"{COMMANDS_DIR.relative_to(REPO_ROOT)}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
