"""orbit - Agent Teams: persistent named agents with file-based JSONL inboxes.

Orbit is a lightweight local coding agent that runs in your terminal.
It combines:
- In-memory todo tracking (TodoWrite)
- File-based persistent task management
- Background command execution with notification injection
- Skill loading from SKILL.md files
- Subagent delegation for isolated work
- Teammate agents with work/idle lifecycle and auto-claim
- Conversation compression (microcompact + auto-compact)
- Messaging via file-based JSONL inboxes
- Shutdown and plan approval protocols

Usage:
    orbit              # Run the interactive CLI
    python -m orbit    # Run as module
"""

__version__ = "0.1.0"

from .background import BackgroundManager
from .bus import MessageBus, VALID_MSG_TYPES
from .cli import main
from .compress import Compressor
from .core import agent_loop, build_system_prompt
from .manager import TeammateManager
from .skills import SkillLoader
from .subagent import run_subagent
from .task_mgr import TaskManager
from .todo import TodoManager
from .tools import (
    build_tool_handlers,
    get_tools_for_lead,
    get_tools_for_teammate,
)

__all__ = [
    # CLI
    "main",
    # Core
    "agent_loop",
    "build_system_prompt",
    # Managers
    "TodoManager",
    "TaskManager",
    "BackgroundManager",
    "SkillLoader",
    "Compressor",
    "MessageBus",
    "TeammateManager",
    # Tools
    "build_tool_handlers",
    "get_tools_for_lead",
    "get_tools_for_teammate",
    # Subagent
    "run_subagent",
    # Constants
    "VALID_MSG_TYPES",
]
