"""orbit - Agent Teams: Persistent named agents with file-based JSONL inboxes.

Usage:
    orbit              # Run the interactive CLI
    python -m orbit    # Run as module
"""

__version__ = "0.1.0"

from .bus import MessageBus, VALID_MSG_TYPES
from .manager import TeammateManager
from .core import agent_loop
from .cli import main

__all__ = [
    "MessageBus",
    "VALID_MSG_TYPES",
    "TeammateManager",
    "agent_loop",
    "main",
]
