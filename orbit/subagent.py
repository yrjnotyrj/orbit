"""Subagent: spawn a short-lived agent for isolated exploration or work.

Unlike teammates, subagents run synchronously, return a summary, and
are destroyed. They have a limited toolset (bash + read_file for
Explore; + write_file/edit_file for general-purpose).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import Anthropic

from .tools import _run_bash, _run_edit, _run_read, _run_write


def run_subagent(
    prompt: str,
    *,
    client: "Anthropic",
    model: str,
    workdir: Path,
    agent_type: str = "Explore",
    max_turns: int = 30,
) -> str:
    """Run a short-lived subagent and return its summary.

    The subagent has a restricted toolset:
    - Explore: bash, read_file only (read-only exploration)
    - general-purpose: + write_file, edit_file (can modify files)

    Args:
        prompt: Task description for the subagent.
        client: Anthropic API client.
        model: Model ID string.
        workdir: Workspace root directory.
        agent_type: "Explore" (read-only) or "general-purpose" (read-write).
        max_turns: Maximum tool-use turns before forced return.

    Returns:
        The subagent's final text response, or an error string.
    """
    # ---- tool definitions ----
    sub_tools: list[dict] = [
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
    ]

    if agent_type != "Explore":
        sub_tools += [
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
        ]

    # ---- tool handlers ----
    sub_handlers: dict[str, callable] = {
        "bash": lambda **kw: _run_bash(kw["command"], workdir),
        "read_file": lambda **kw: _run_read(kw["path"], workdir),
        "write_file": lambda **kw: _run_write(kw["path"], kw["content"], workdir),
        "edit_file": lambda **kw: _run_edit(
            kw["path"], kw["old_text"], kw["new_text"], workdir
        ),
    }

    # ---- agent loop ----
    sub_msgs: list[dict] = [{"role": "user", "content": prompt}]
    resp = None

    for _ in range(max_turns):
        resp = client.messages.create(
            model=model,
            messages=sub_msgs,
            tools=sub_tools,
            max_tokens=8000,
        )
        sub_msgs.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            break

        results: list[dict] = []
        for block in resp.content:
            if block.type == "tool_use":
                handler = sub_handlers.get(
                    block.name,
                    lambda **kw: "Unknown tool",
                )
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(handler(**block.input))[:50000],
                })
        sub_msgs.append({"role": "user", "content": results})

    if resp:
        texts = [
            b.text for b in resp.content
            if hasattr(b, "text") and b.text
        ]
        return "".join(texts) or "(no summary)"

    return "(subagent failed)"
