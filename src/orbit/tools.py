"""Tool implementations and definitions for orbit agent teams.

Provides:
- Base tool implementations (bash, read_file, write_file, edit_file)
- Tool definitions for lead and teammates
- Tool handler dispatch for the lead agent loop
"""

import json
import subprocess
from pathlib import Path

from .bus import VALID_MSG_TYPES


# ---------------------------------------------------------------------------
# Base tool implementations (these base tools are unchanged from s02)
# ---------------------------------------------------------------------------

def _safe_path(p: str, workdir: Path) -> Path:
    """Resolve and validate that a path is within the workspace.

    Args:
        p: Relative or absolute path string.
        workdir: The workspace root directory.

    Returns:
        Resolved absolute path.

    Raises:
        ValueError: If the resolved path escapes the workspace.
    """
    path = (workdir / p).resolve()
    if not path.is_relative_to(workdir):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def _run_bash(command: str, workdir: Path) -> str:
    """Run a shell command in the workspace directory.

    Blocks dangerous commands for safety.

    Args:
        command: The shell command to execute.
        workdir: Working directory for command execution.

    Returns:
        Command output (stdout + stderr), truncated to 50000 chars.
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def _run_read(path: str, workdir: Path, limit: int = None) -> str:
    """Read file contents from the workspace.

    Args:
        path: File path relative to workspace.
        workdir: Workspace root directory.
        limit: Optional maximum number of lines to read.

    Returns:
        File contents as string, truncated to 50000 chars.
    """
    try:
        lines = _safe_path(path, workdir).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def _run_write(path: str, content: str, workdir: Path) -> str:
    """Write content to a file in the workspace.

    Creates parent directories if they don't exist.

    Args:
        path: File path relative to workspace.
        content: Text content to write.
        workdir: Workspace root directory.

    Returns:
        Status string with bytes written.
    """
    try:
        fp = _safe_path(path, workdir)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def _run_edit(path: str, old_text: str, new_text: str, workdir: Path) -> str:
    """Replace the first occurrence of exact text in a file.

    Args:
        path: File path relative to workspace.
        old_text: Exact text to find and replace.
        new_text: Replacement text.
        workdir: Workspace root directory.

    Returns:
        Status string describing the result.
    """
    try:
        fp = _safe_path(path, workdir)
        c = fp.read_text(encoding="utf-8")
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def get_tools_for_lead() -> list[dict]:
    """Get tool definitions for the team lead agent (9 tools)."""
    return [
        {
            "name": "bash",
            "description": "Run a shell command.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file contents.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "edit_file",
            "description": "Replace exact text in file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
        {
            "name": "spawn_teammate",
            "description": "Spawn a persistent teammate that runs in its own thread.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["name", "role", "prompt"],
            },
        },
        {
            "name": "list_teammates",
            "description": "List all teammates with name, role, status.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "send_message",
            "description": "Send a message to a teammate's inbox.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "content": {"type": "string"},
                    "msg_type": {
                        "type": "string",
                        "enum": sorted(VALID_MSG_TYPES),
                    },
                },
                "required": ["to", "content"],
            },
        },
        {
            "name": "read_inbox",
            "description": "Read and drain the lead's inbox.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "broadcast",
            "description": "Send a message to all teammates.",
            "input_schema": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },
    ]


def get_tools_for_teammate() -> list[dict]:
    """Get tool definitions for teammate agents (6 tools).

    Teammates have a subset of tools: they cannot spawn other teammates,
    list teammates, or broadcast.
    """
    return [
        {
            "name": "bash",
            "description": "Run a shell command.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file contents.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "edit_file",
            "description": "Replace exact text in file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
        {
            "name": "send_message",
            "description": "Send message to a teammate.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "content": {"type": "string"},
                    "msg_type": {
                        "type": "string",
                        "enum": sorted(VALID_MSG_TYPES),
                    },
                },
                "required": ["to", "content"],
            },
        },
        {
            "name": "read_inbox",
            "description": "Read and drain your inbox.",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]


def get_tool_handlers(
    bus: "MessageBus",
    team: "TeammateManager",
    workdir: Path,
) -> dict[str, callable]:
    """Get tool handler dispatch for the team lead agent loop.

    Each handler is a callable that receives **kwargs matching the tool's
    input_schema properties. Handlers are closures that capture bus, team,
    and workdir from the calling context.

    Args:
        bus: The MessageBus instance for communication.
        team: The TeammateManager instance for teammate lifecycle.
        workdir: The current workspace root directory.

    Returns:
        Dictionary mapping tool names to handler callables.
    """
    return {
        "bash":            lambda **kw: _run_bash(kw["command"], workdir),
        "read_file":       lambda **kw: _run_read(kw["path"], workdir, kw.get("limit")),
        "write_file":      lambda **kw: _run_write(kw["path"], kw["content"], workdir),
        "edit_file":       lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"], workdir),
        "spawn_teammate":  lambda **kw: team.spawn(kw["name"], kw["role"], kw["prompt"]),
        "list_teammates":  lambda **kw: team.list_all(),
        "send_message":    lambda **kw: bus.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
        "read_inbox":      lambda **kw: json.dumps(bus.read_inbox("lead"), indent=2, ensure_ascii=False),
        "broadcast":       lambda **kw: bus.broadcast("lead", kw["content"], team.member_names()),
    }
