"""Core agent loop for the orbit team lead.

The lead agent orchestrates everything: it manages the conversation,
runs compression, drains background notifications, checks inboxes,
executes tool calls, and nudges for todo updates.

    +------------------------------------------------------------------+
    |                        FULL AGENT                                 |
    |                                                                   |
    |  System prompt (skills, task-first + optional todo nag)          |
    |                                                                   |
    |  Before each LLM call:                                            |
    |  +--------------------+  +------------------+  +--------------+  |
    |  | Microcompact       |  | Drain bg         |  | Check inbox  |  |
    |  | Auto-compact       |  | notifications    |  |              |  |
    |  +--------------------+  +------------------+  +--------------+  |
    |                                                                   |
    |  Tool dispatch:                                                   |
    |  bash | read | write | edit | TodoWrite | task | load_skill      |
    |  compress | bg_run | bg_check | task_crud | spawn_tm | msg       |
    |  shutdown | plan | idle | claim                                   |
    +------------------------------------------------------------------+
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anthropic import Anthropic

    from .background import BackgroundManager
    from .bus import MessageBus
    from .compress import Compressor
    from .manager import TeammateManager
    from .skills import SkillLoader
    from .todo import TodoManager


def build_system_prompt(
    workdir: Path,
    skills: "SkillLoader",
) -> str:
    """Build the system prompt with dynamic skill descriptions.

    Args:
        workdir: Workspace root directory.
        skills: SkillLoader instance for available skills listing.

    Returns:
        Complete system prompt string.
    """
    return (
        f"You are a coding agent at {workdir}. "
        f"Use tools to solve tasks. "
        f"Prefer task_create/task_update/task_list for multi-step work. "
        f"Use TodoWrite for short checklists. "
        f"Use task for subagent delegation. "
        f"Use load_skill for specialized knowledge. "
        f"Skills:\n{skills.descriptions()}"
    )


def agent_loop(
    messages: list[dict[str, Any]],
    *,
    client: "Anthropic",
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    handlers: dict[str, callable],
    compressor: "Compressor",
    todo: "TodoManager",
    bg: "BackgroundManager",
    bus: "MessageBus",
) -> None:
    """Run the team lead's full agent loop.

    Each iteration:
    1. Microcompact old tool results
    2. Auto-compact if token threshold exceeded
    3. Drain background task notifications
    4. Check lead inbox for teammate messages
    5. Call LLM with tools
    6. Execute tool calls
    7. Inject todo nag if needed
    8. Handle manual compress

    The loop terminates when the LLM returns stop_reason != "tool_use",
    or when a manual compress is triggered.

    Args:
        messages: Message history (mutated in place — final assistant
                  message left for the caller to display).
        client: Anthropic API client.
        model: Model ID string.
        system: System prompt string.
        tools: Tool definitions list.
        handlers: Tool handler dispatch dict.
        compressor: Compressor instance.
        todo: TodoManager instance.
        bg: BackgroundManager instance.
        bus: MessageBus instance.
    """
    rounds_without_todo = 0

    while True:
        # ---- s06: compression pipeline ----
        compressor.microcompact(messages)
        if compressor.estimate_tokens(messages) > compressor.threshold:
            print("[auto-compact triggered]")
            messages[:] = compressor.auto_compact(messages)

        # ---- s08: drain background notifications ----
        notifs = bg.drain()
        if notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}"
                for n in notifs
            )
            messages.append({
                "role": "user",
                "content": (
                    f"<background-results>\n{txt}\n</background-results>"
                ),
            })

        # ---- s10: check lead inbox ----
        inbox = bus.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": (
                    f"<inbox>{json.dumps(inbox, indent=2, ensure_ascii=False)}</inbox>"
                ),
            })

        # ---- LLM call ----
        response = client.messages.create(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        # ---- Tool execution ----
        results: list[dict[str, Any]] = []
        used_todo = False
        manual_compress = False

        for block in response.content:
            if block.type == "tool_use":
                if block.name == "compress":
                    manual_compress = True

                handler = handlers.get(block.name)
                try:
                    output = (
                        handler(**block.input)
                        if handler
                        else f"Unknown tool: {block.name}"
                    )
                except Exception as e:
                    output = f"Error: {e}"

                print(f"> {block.name}:")
                print(str(output)[:200])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })

                if block.name == "TodoWrite":
                    used_todo = True

        # ---- s03: nag reminder ----
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if todo.has_open_items() and rounds_without_todo >= 3:
            results.append({
                "type": "text",
                "text": "<reminder>Update your todos.</reminder>",
            })

        messages.append({"role": "user", "content": results})

        # ---- s06: manual compress ----
        if manual_compress:
            print("[manual compact]")
            messages[:] = compressor.auto_compact(messages)
            return
