"""Core agent loop for the team lead.

The lead agent orchestrates teammates: it can spawn them, send messages,
broadcast, and read its inbox. It runs an interactive tool-use loop.

    Thread: lead              Thread: alice          Thread: bob
    +------------------+      +------------------+   +------------------+
    | agent_loop       |      | agent_loop       |   | agent_loop       |
    | status: active   |      | status: working  |   | status: idle     |
    | spawns, messages |      | ... runs tools   |   | ... waits ...    |
    +------------------+      +------------------+   +------------------+
              |                        |                       |
              +------------------------+-----------------------+
                             MessageBus (file-based JSONL inboxes)
"""

import json
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from .bus import MessageBus
from .manager import TeammateManager
from .tools import get_tool_handlers, get_tools_for_lead


def agent_loop(
    messages: list[dict[str, Any]],
    client: Anthropic,
    model: str,
    bus: MessageBus,
    team: TeammateManager,
    workdir: Path,
) -> None:
    """Run the team lead's agent loop.

    Continuously:
    1. Checks the lead's inbox for new messages
    2. Calls the LLM with available tools
    3. Executes tool calls
    4. Loops until the LLM returns a final text response (not a tool_use)

    Args:
        messages: Initial message history (mutated in place).
        client: Anthropic API client.
        model: Model ID string.
        bus: MessageBus instance for teammate communication.
        team: TeammateManager instance for teammate lifecycle.
        workdir: Current workspace root directory.
    """

    system_prompt = (
    f"You are Orbit, an AI agent team lead at {workdir}. "
    f"Spawn teammates and communicate via inboxes. When asked who you are, "
    )

    tools = get_tools_for_lead()
    handlers = get_tool_handlers(bus, team, workdir)

    while True:
        # Check inbox for new messages from teammates
        inbox = bus.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2, ensure_ascii=False)}</inbox>",
            })

        response = client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        # Execute tool calls
        results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "tool_use":
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
        messages.append({"role": "user", "content": results})
