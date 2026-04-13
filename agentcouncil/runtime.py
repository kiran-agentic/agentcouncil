"""agentcouncil.runtime — OutsideRuntime with read-only tool loop and security.

Provides:
    ToolSecurityError  — raised on path traversal, symlink escape, or blocked extension
    TokenBudgetExceeded — raised when per-turn char budget is exceeded
    OutsideRuntime     — secure tool-loop execution layer between LLM and workspace files

Private helpers (importable for testing):
    _validate_path, _check_extension_allowlist, _parse_textual_actions
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from agentcouncil.providers import OutsideProvider, ProviderResponse, ToolCall

__all__ = ["OutsideRuntime", "ToolSecurityError", "TokenBudgetExceeded"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ToolSecurityError(Exception):
    """Raised when a tool call fails path validation or extension checks."""
    pass


class TokenBudgetExceeded(Exception):
    """Raised when the serialized message char count exceeds the per-turn budget."""
    pass


# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

_BLOCKED_NAMES: frozenset[str] = frozenset({
    # Environment / secrets
    ".env", ".envrc", ".netrc",
    # Version control credentials
    ".git-credentials", ".gitcredentials",
    # Package manager auth
    ".npmrc", ".pypirc",
    # Docker
    ".dockercfg",
    # SSH keys (common filenames without blocked extensions)
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
})
_BLOCKED_PREFIXES: tuple[str, ...] = (
    ".env.",       # .env.local, .env.production, .env.development, etc.
)
_BLOCKED_EXTENSIONS: frozenset[str] = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".crt", ".cer",
    ".secret", ".secrets",
})
_BLOCKED_PATH_SEGMENTS: frozenset[str] = frozenset({
    ".ssh", ".aws", ".docker", ".gnupg",
})

_MAX_READ_BYTES = 50 * 1024  # 50 KB truncation for safety


# ---------------------------------------------------------------------------
# Security helpers (private, but importable for tests)
# ---------------------------------------------------------------------------


def _validate_path(raw_path: str, workspace: str) -> str:
    """Resolve raw_path relative to workspace; reject any escape.

    Uses os.path.realpath() to follow symlinks before checking the
    boundary, so symlinks pointing outside the workspace are rejected.

    Args:
        raw_path  — Relative (or absolute) path from the model
        workspace — Absolute workspace directory (will be realpath'd)

    Returns:
        Resolved absolute path guaranteed to be inside workspace.

    Raises:
        ToolSecurityError: if the resolved path escapes the workspace.
    """
    workspace_real = os.path.realpath(workspace)
    joined = os.path.join(workspace_real, raw_path)
    resolved = os.path.realpath(joined)

    # Allow workspace root itself, or anything inside it
    inside = (
        resolved == workspace_real
        or resolved.startswith(workspace_real + os.sep)
    )
    if not inside:
        raise ToolSecurityError(
            f"Path escape detected: {raw_path!r} resolves to {resolved!r} "
            f"which is outside workspace {workspace_real!r}"
        )
    return resolved


def _check_extension_allowlist(resolved_path: str) -> None:
    """Reject paths whose name, extension, prefix, or path segment is blocked.

    Args:
        resolved_path — Absolute, already-validated path string.

    Raises:
        ToolSecurityError: if the file matches a blocked pattern.
    """
    p = Path(resolved_path)
    if p.name in _BLOCKED_NAMES:
        raise ToolSecurityError(
            f"Blocked file name: {p.name!r} is on the security blocklist"
        )
    if any(p.name.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        raise ToolSecurityError(
            f"Blocked file name prefix: {p.name!r} matches a blocked prefix"
        )
    if p.suffix.lower() in _BLOCKED_EXTENSIONS:
        raise ToolSecurityError(
            f"Blocked file extension: {p.suffix.lower()!r} is on the security blocklist"
        )
    if any(segment in _BLOCKED_PATH_SEGMENTS for segment in p.parts):
        raise ToolSecurityError(
            f"Blocked path segment: path contains a sensitive directory"
        )


# ---------------------------------------------------------------------------
# Textual action protocol
# ---------------------------------------------------------------------------

# Anchored to line start (re.MULTILINE) to prevent false positives from prose mentions.
_ACTION_RE = re.compile(
    r"^(READ_FILE|LIST_FILES|SEARCH_REPO|READ_DIFF)\s+(\w+=\S+(?:\s+\w+=\S+)*)",
    re.MULTILINE | re.IGNORECASE,
)


def _parse_textual_actions(text: str) -> list[ToolCall]:
    """Parse textual action commands from a model response.

    Recognises lines matching ACTION_NAME key=value [key=value ...] and converts
    them to ToolCall objects.  The regex is anchored to line start (re.MULTILINE)
    so casual prose mentions of READ_FILE in the middle of a sentence are ignored.

    Supported actions (case-insensitive, normalised to lowercase):
        READ_FILE, LIST_FILES, SEARCH_REPO, READ_DIFF

    Args:
        text — Raw text content from a provider response.

    Returns:
        Ordered list of ToolCall objects; empty list if no actions found.
    """
    tool_calls: list[ToolCall] = []
    for i, match in enumerate(_ACTION_RE.finditer(text)):
        action_name = match.group(1).lower()
        args_str = match.group(2)
        arguments: dict[str, Any] = {}
        for pair in args_str.split():
            if "=" in pair:
                key, _, value = pair.partition("=")
                arguments[key] = value
        tool_calls.append(ToolCall(id=f"textual-{i}", name=action_name, arguments=arguments))
    return tool_calls


# ---------------------------------------------------------------------------
# Private tool implementations
# ---------------------------------------------------------------------------


async def _tool_list_files(workspace: str, path: str = ".") -> str:
    """List files/directories at path inside workspace.

    Args:
        workspace — Realpath'd workspace directory
        path      — Relative path to list (default: workspace root)

    Returns:
        Newline-separated listing, or error string on failure.
    """
    try:
        resolved = _validate_path(path, workspace)
        entries = os.listdir(resolved)
        return "\n".join(sorted(entries))
    except ToolSecurityError:
        raise
    except OSError as e:
        return f"list_files error: {e}"


async def _tool_read_file(workspace: str, path: str) -> str:
    """Read and return the contents of a file inside workspace (50 KB max).

    Args:
        workspace — Realpath'd workspace directory
        path      — Relative path to the file

    Returns:
        File content as string (truncated at 50 KB if needed).

    Raises:
        ToolSecurityError: on path escape or blocked extension.
    """
    resolved = _validate_path(path, workspace)
    _check_extension_allowlist(resolved)
    try:
        with open(resolved, "rb") as f:
            raw = f.read(_MAX_READ_BYTES)
        return raw.decode("utf-8", errors="replace")
    except OSError as e:
        return f"read_file error: {e}"


def _filter_blocked_paths_from_grep(output: str, workspace: str) -> str:
    """Remove grep output lines that reference blocked files.

    Each grep line is typically formatted as "path:line:content".
    We check the path portion against the blocked names/extensions.
    """
    filtered_lines = []
    for line in output.splitlines():
        # grep -rn output: "filepath:linenum:content"
        colon_idx = line.find(":")
        if colon_idx == -1:
            # Colon-less lines include diagnostics like "Binary file .env matches".
            # Check every whitespace token for blocked names/extensions.
            if _line_references_blocked_file(line):
                continue
            filtered_lines.append(line)
            continue
        file_part = line[:colon_idx]
        p = Path(file_part)
        if _is_blocked_path(p):
            continue  # skip lines from blocked files
        filtered_lines.append(line)
    return "\n".join(filtered_lines)


def _is_blocked_path(p: Path) -> bool:
    """Check if a Path matches any blocked pattern."""
    if p.name in _BLOCKED_NAMES:
        return True
    if any(p.name.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        return True
    if p.suffix.lower() in _BLOCKED_EXTENSIONS:
        return True
    if any(segment in _BLOCKED_PATH_SEGMENTS for segment in p.parts):
        return True
    return False


def _line_references_blocked_file(line: str) -> bool:
    """Check if any token in a line references a blocked file name or extension."""
    for token in line.strip().split():
        if _is_blocked_path(Path(token)):
            return True
    return False


async def _tool_search_repo(workspace: str, pattern: str, path: str = ".") -> str:
    """Search workspace files for a regex pattern using grep.

    Args:
        workspace — Realpath'd workspace directory
        pattern   — grep-compatible regex
        path      — Relative path to search within (default: workspace root)

    Returns:
        grep output (truncated at 50 KB), or error string.
        Lines referencing blocked files are filtered from the output.
    """
    try:
        resolved = _validate_path(path, workspace)
    except ToolSecurityError:
        raise
    # If searching a specific file, check extension allowlist
    if os.path.isfile(resolved):
        _check_extension_allowlist(resolved)
    try:
        result = subprocess.run(
            ["grep", "-rn", pattern, resolved],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr or ""
        # Filter out any grep matches from blocked files
        output = _filter_blocked_paths_from_grep(output, workspace)
        return output[:_MAX_READ_BYTES]
    except subprocess.TimeoutExpired:
        return "search_repo error: grep timed out"
    except OSError as e:
        return f"search_repo error: {e}"


def _filter_blocked_paths_from_diff(output: str) -> str:
    """Remove diff hunks that reference blocked files.

    Diff sections start with 'diff --git a/path b/path'. If the path
    is a blocked file, skip everything until the next diff header.
    """
    lines = output.splitlines()
    result_lines = []
    skip = False
    for line in lines:
        if line.startswith("diff --git "):
            # Extract path from "diff --git a/path b/path"
            parts = line.split()
            # parts: ['diff', '--git', 'a/path', 'b/path']
            skip = False
            if len(parts) >= 4:
                file_path = parts[3].lstrip("b/")
                p = Path(file_path)
                if _is_blocked_path(p):
                    skip = True
                    continue
        if skip:
            continue
        result_lines.append(line)
    return "\n".join(result_lines)


async def _tool_read_diff(workspace: str, path: str = ".") -> str:
    """Return git diff HEAD for a path inside workspace.

    Args:
        workspace — Realpath'd workspace directory
        path      — Relative path to diff (default: workspace root)

    Returns:
        git diff output (truncated at 50 KB), or error string if git unavailable.
        Diffs of blocked files are filtered from the output.
    """
    try:
        resolved = _validate_path(path, workspace)
    except ToolSecurityError:
        raise
    # If diffing a specific file, check extension allowlist
    if os.path.isfile(resolved):
        _check_extension_allowlist(resolved)
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", resolved],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=workspace,
        )
        output = result.stdout or result.stderr or ""
        # Filter diff hunks for blocked files (diff --- a/path and +++ b/path headers)
        output = _filter_blocked_paths_from_diff(output)
        return output[:_MAX_READ_BYTES]
    except FileNotFoundError:
        return "read_diff error: git not available"
    except subprocess.TimeoutExpired:
        return "read_diff error: git diff timed out"
    except OSError as e:
        return f"read_diff error: {e}"


# ---------------------------------------------------------------------------
# Tool registry and specs
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: dict[str, Callable] = {
    "list_files": _tool_list_files,
    "search_repo": _tool_search_repo,
    "read_file": _tool_read_file,
    "read_diff": _tool_read_diff,
}

_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a path inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to list (default: workspace root '.')",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file inside the workspace (max 50 KB).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_repo",
            "description": "Search files in the workspace for a regex pattern using grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "grep-compatible regex to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path to search within (default: '.')",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_diff",
            "description": "Return the git diff HEAD for a path inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to diff (default: workspace root '.')",
                    },
                },
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# OutsideRuntime
# ---------------------------------------------------------------------------


class OutsideRuntime:
    """Secure execution layer between LLM responses and workspace file access.

    Responsibilities:
      - Enforces per-turn character budget on the message list
      - Runs a tool loop: dispatches tool_calls from the model and appends results
      - Limits tool call retries to MAX_TOOL_RETRIES; degrades to text-only after
      - Validates all file paths (traversal + symlink) before execution
      - Enforces extension blocklist (no .env, .pem, .key, etc.)

    Args:
        provider              — An OutsideProvider instance (e.g. StubProvider)
        workspace             — Directory tools are scoped to (realpath'd at init)
        char_budget           — Max serialized message chars per turn (default 100 000)
        allow_textual_protocol — Reserved for future text-based tool fallback
    """

    MAX_TOOL_RETRIES: int = 3

    def __init__(
        self,
        provider: OutsideProvider,
        workspace: str,
        char_budget: int = 100_000,
        allow_textual_protocol: bool = False,
    ) -> None:
        self._provider = provider
        self._workspace = os.path.realpath(workspace)
        self._char_budget = char_budget
        self._allow_textual_protocol = allow_textual_protocol
        self._tool_specs = _TOOL_SPECS

    async def run_turn(self, messages: list[dict[str, Any]]) -> str:
        """Execute a single deliberation turn with the provider.

        Runs the tool loop:
          1. Check char budget on the serialized messages.
          2. Call provider.chat_complete with tools (up to MAX_TOOL_RETRIES times).
          3. If response has tool_calls, execute them and append results.
          4. Once retries == MAX_TOOL_RETRIES, strip tools from next call.
          5. Return the text content of the first non-tool-call response.

        Args:
            messages — OpenAI-style message list to send to the provider.

        Returns:
            Text content from the final provider response.

        Raises:
            TokenBudgetExceeded: if serialized messages exceed char_budget.
        """
        # Budget check
        serialized = json.dumps(messages)
        if len(serialized) > self._char_budget:
            raise TokenBudgetExceeded(
                f"Messages ({len(serialized)} chars) exceed char_budget ({self._char_budget})"
            )

        retries = 0
        msgs = list(messages)  # local copy — we append tool results

        while True:
            tools = self._tool_specs if retries < self.MAX_TOOL_RETRIES else None
            response: ProviderResponse = await self._provider.chat_complete(msgs, tools=tools)

            if response.tool_calls and retries < self.MAX_TOOL_RETRIES:
                # Execute tools and append results
                tool_results = await self._execute_tools(response.tool_calls)
                # Append assistant message with tool_calls
                msgs.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in response.tool_calls
                    ],
                })
                # Append tool results
                for result in tool_results:
                    msgs.append(result)
                retries += 1
                continue

            # No native tool_calls — check textual protocol (opt-in only)
            if self._allow_textual_protocol and retries < self.MAX_TOOL_RETRIES:
                textual_calls = _parse_textual_actions(response.content or "")
                if textual_calls:
                    tool_results = await self._execute_tools(textual_calls)
                    # Append assistant message (content only — no tool_calls field for textual)
                    msgs.append({
                        "role": "assistant",
                        "content": response.content or "",
                    })
                    # Append tool results
                    for result in tool_results:
                        msgs.append(result)
                    retries += 1
                    continue

            # No tool_calls, no textual actions (or disabled) — return text content
            return response.content or ""

    async def _execute_tools(self, tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
        """Dispatch tool calls through the registry and return tool result messages.

        Catches ToolSecurityError so a single bad path does not crash the loop.
        Unknown tool names return an error string.

        Args:
            tool_calls — List of ToolCall objects from the provider response.

        Returns:
            List of OpenAI-style tool result messages (role: "tool").
        """
        results = []
        for tc in tool_calls:
            try:
                handler = _TOOL_REGISTRY.get(tc.name)
                if handler is None:
                    content = f"Error: unknown tool {tc.name!r}"
                else:
                    content = await handler(self._workspace, **tc.arguments)
            except ToolSecurityError as e:
                content = f"Security error: {e}"
            except Exception as e:
                content = f"Tool error: {e}"
            results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(content),
            })
        return results
