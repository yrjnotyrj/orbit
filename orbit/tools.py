"""Tool implementations, definitions, and handler dispatch.

Provides:
- Base tool implementations (bash, read_file, write_file, edit_file)
- Tool definitions for the lead agent (23 tools)
- Tool definitions for teammates (7 tools)
- Handler construction for the lead agent loop
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .bus import VALID_MSG_TYPES

if TYPE_CHECKING:
    from .background import BackgroundManager
    from .bus import MessageBus
    from .compress import Compressor
    from .manager import TeammateManager
    from .skills import SkillLoader
    from .task_mgr import TaskManager
    from .todo import TodoManager


# ======================================================================
# Base tool implementations
# ======================================================================

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

    Blocks known dangerous commands for safety.

    Args:
        command: The shell command to execute.
        workdir: Working directory for command execution.

    Returns:
        Command output (stdout + stderr), truncated to 50000 chars.
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
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


def _run_read(path: str, workdir: Path, limit: int | None = None) -> str:
    """Read file contents from the workspace.

    Args:
        path: File path relative to workspace.
        workdir: Workspace root directory.
        limit: Optional maximum number of lines to read.

    Returns:
        File contents as string, truncated to 50000 chars.
    """
    try:
        lines = (
            _safe_path(path, workdir)
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if limit is not None and limit < len(lines):
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
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def _run_edit(
    path: str,
    old_text: str,
    new_text: str,
    workdir: Path,
) -> str:
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


# ======================================================================
# Tool definitions — Lead agent (23 tools)
# ======================================================================

def get_tools_for_lead() -> list[dict[str, Any]]:
    """Get all tool definitions for the team lead agent.

    The lead has the full toolset: filesystem, task management,
    subagent delegation, skill loading, compression, background
    execution, teammate management, messaging, plan approval,
    and shutdown requests.

    Returns:
        List of tool definition dicts.
    """
    return [
        # ---- Filesystem ----
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
            "description": "Write content to a file.",
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
            "description": "Replace exact text in a file.",
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
        # ---- Todo tracking ----
        {
            "name": "TodoWrite",
            "description": "Update the in-memory task tracking list.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "pending",
                                        "in_progress",
                                        "completed",
                                    ],
                                },
                                "activeForm": {"type": "string"},
                            },
                            "required": ["content", "status", "activeForm"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
        # ---- Subagent delegation ----
        {
            "name": "task",
            "description": "Spawn a subagent for isolated exploration or work.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "agent_type": {
                        "type": "string",
                        "enum": ["Explore", "general-purpose"],
                    },
                },
                "required": ["prompt"],
            },
        },
        # ---- Skills ----
        {
            "name": "load_skill",
            "description": "Load specialized knowledge by name.",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        # ---- Compression ----
        {
            "name": "compress",
            "description": "Manually compress the conversation context.",
            "input_schema": {"type": "object", "properties": {}},
        },
        # ---- Background execution ----
        {
            "name": "background_run",
            "description": "Run a command in a background thread.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
        },
        {
            "name": "check_background",
            "description": "Check background task status.",
            "input_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
            },
        },
        # ---- File-based task management ----
        {
            "name": "task_create",
            "description": "Create a persistent file task.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["subject"],
            },
        },
        {
            "name": "task_get",
            "description": "Get task details by ID.",
            "input_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
        {
            "name": "task_update",
            "description": "Update task status or dependencies.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_progress",
                            "completed",
                            "deleted",
                        ],
                    },
                    "add_blocked_by": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "remove_blocked_by": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["task_id"],
            },
        },
        {
            "name": "task_list",
            "description": "List all tasks.",
            "input_schema": {"type": "object", "properties": {}},
        },
        # ---- Teammate management ----
        {
            "name": "spawn_teammate",
            "description": "Spawn a persistent autonomous teammate.",
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
            "description": "List all teammates.",
            "input_schema": {"type": "object", "properties": {}},
        },
        # ---- Messaging ----
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
        # ---- Shutdown & plan approval (s10) ----
        {
            "name": "shutdown_request",
            "description": "Request a teammate to shut down.",
            "input_schema": {
                "type": "object",
                "properties": {"teammate": {"type": "string"}},
                "required": ["teammate"],
            },
        },
        {
            "name": "plan_approval",
            "description": "Approve or reject a teammate's plan.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "approve": {"type": "boolean"},
                    "feedback": {"type": "string"},
                },
                "required": ["request_id", "approve"],
            },
        },
        # ---- Idle & claim ----
        {
            "name": "idle",
            "description": "Enter idle state (lead: no-op).",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "claim_task",
            "description": "Claim a task from the board.",
            "input_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    ]


# ======================================================================
# Tool definitions — Teammate agents (7 tools)
# ======================================================================

def get_tools_for_teammate() -> list[dict[str, Any]]:
    """Get tool definitions for teammate agents.

    Teammates have a restricted toolset: filesystem tools,
    messaging, idle, and task claiming. They cannot spawn
    sub-agents or manage other teammates.

    Returns:
        List of tool definition dicts.
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
            "description": "Write content to a file.",
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
            "description": "Replace exact text in a file.",
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
            "description": "Send a message to a teammate.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["to", "content"],
            },
        },
        {
            "name": "idle",
            "description": "Signal that you have no more work to do right now.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "claim_task",
            "description": "Claim a task by its ID.",
            "input_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    ]


# ======================================================================
# Handler construction — Lead agent
# ======================================================================

# Protocol state (module-level, shared across the lead agent loop)
# These are mutated by the plan_approval and shutdown_request handlers.
plan_requests: dict[str, dict[str, Any]] = {}
shutdown_requests: dict[str, dict[str, Any]] = {}


def build_tool_handlers(
    *,
    todo: "TodoManager",
    task_mgr: "TaskManager",
    bg: "BackgroundManager",
    skills: "SkillLoader",
    compressor: "Compressor",
    team: "TeammateManager",
    bus: "MessageBus",
    workdir: Path,
    run_subagent_fn: callable,
) -> dict[str, callable]:
    """Build the complete tool handler dispatch for the lead agent.

    Each handler is a callable(**kwargs) -> str. The handler dictionary
    maps tool names to their implementations.

    Args:
        todo: TodoManager instance.
        task_mgr: TaskManager instance.
        bg: BackgroundManager instance.
        skills: SkillLoader instance.
        compressor: Compressor instance (for microcompact/auto_compact).
        team: TeammateManager instance.
        bus: MessageBus instance.
        workdir: Workspace root directory.
        run_subagent_fn: The run_subagent function (pre-bound with client/model).

    Returns:
        Dictionary mapping tool names to handler callables.
    """

    def _handle_shutdown_request(teammate: str) -> str:
        """Handle a shutdown_request tool call."""
        import uuid as _uuid
        req_id = str(_uuid.uuid4())[:8]
        shutdown_requests[req_id] = {
            "target": teammate,
            "status": "pending",
        }
        bus.send(
            "lead",
            teammate,
            "Please shut down.",
            "shutdown_request",
            {"request_id": req_id},
        )
        return f"Shutdown request {req_id} sent to '{teammate}'"

    def _handle_plan_review(
        request_id: str,
        approve: bool,
        feedback: str = "",
    ) -> str:
        """Handle a plan_approval tool call."""
        req = plan_requests.get(request_id)
        if not req:
            return f"Error: Unknown plan request_id '{request_id}'"
        req["status"] = "approved" if approve else "rejected"
        bus.send(
            "lead",
            req["from"],
            feedback,
            "plan_approval_response",
            {
                "request_id": request_id,
                "approve": approve,
                "feedback": feedback,
            },
        )
        return f"Plan {req['status']} for '{req['from']}'"

    return {
        # Filesystem
        "bash":             lambda **kw: _run_bash(kw["command"], workdir),
        "read_file":        lambda **kw: _run_read(kw["path"], workdir, kw.get("limit")),
        "write_file":       lambda **kw: _run_write(kw["path"], kw["content"], workdir),
        "edit_file":        lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"], workdir),
        # Todo
        "TodoWrite":        lambda **kw: todo.update(kw["items"]),
        # Subagent
        "task":             lambda **kw: run_subagent_fn(kw["prompt"], agent_type=kw.get("agent_type", "Explore")),
        # Skills
        "load_skill":       lambda **kw: skills.load(kw["name"]),
        # Compression (actual compression handled in agent loop)
        "compress":         lambda **kw: "Compressing...",
        # Background
        "background_run":   lambda **kw: bg.run(kw["command"], kw.get("timeout", 120)),
        "check_background": lambda **kw: bg.check(kw.get("task_id")),
        # File tasks
        "task_create":      lambda **kw: task_mgr.create(kw["subject"], kw.get("description", "")),
        "task_get":         lambda **kw: task_mgr.get(kw["task_id"]),
        "task_update":      lambda **kw: task_mgr.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("remove_blocked_by")),
        "task_list":        lambda **kw: task_mgr.list_all(),
        # Teammates
        "spawn_teammate":   lambda **kw: team.spawn(kw["name"], kw["role"], kw["prompt"]),
        "list_teammates":   lambda **kw: team.list_all(),
        # Messaging
        "send_message":     lambda **kw: bus.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
        "read_inbox":       lambda **kw: json.dumps(bus.read_inbox("lead"), indent=2, ensure_ascii=False),
        "broadcast":        lambda **kw: bus.broadcast("lead", kw["content"], team.member_names()),
        # Shutdown & plan
        "shutdown_request": lambda **kw: _handle_shutdown_request(kw["teammate"]),
        "plan_approval":    lambda **kw: _handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
        # Idle & claim
        "idle":             lambda **kw: "Lead does not idle.",
        "claim_task":       lambda **kw: task_mgr.claim(kw["task_id"], "lead"),
    }
