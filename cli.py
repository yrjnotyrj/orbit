#!/usr/bin/env python3
"""CLI entry point for orbit agent teams.

Usage:
    orbit              # Interactive CLI
    python -m orbit    # Run as module

Commands:
    /compact  - Manually compress conversation history
    /tasks    - List all file-based tasks
    /team     - List all teammates
    /inbox    - Read lead's inbox
    q, exit   - Quit
"""

from __future__ import annotations

import json
import os
import sys
from functools import partial
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from .background import BackgroundManager
from .bus import MessageBus
from .compress import Compressor
from .core import agent_loop, build_system_prompt
from .manager import TeammateManager
from .skills import SkillLoader
from .subagent import run_subagent
from .task_mgr import TaskManager
from .todo import TodoManager
from .tools import build_tool_handlers, get_tools_for_lead

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

DEFAULT_MODEL = "deepseek-v4-pro"
TOKEN_THRESHOLD = 100000


# ------------------------------------------------------------------
# Environment setup
# ------------------------------------------------------------------

def _get_required_env(name: str) -> str:
    """Get a required environment variable, exiting with a clear message.

    Args:
        name: The environment variable name.

    Returns:
        The environment variable value.

    Raises:
        SystemExit: If the variable is not set.
    """
    value = os.getenv(name)
    if not value:
        print(f"Error: {name} is not set.", file=sys.stderr)
        print(
            f"Please set {name} in your environment or .env file.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def _setup_client() -> tuple[Anthropic, str]:
    """Set up the Anthropic client from environment variables.

    Loads .env file, validates required variables, and creates the
    client. Supports custom ANTHROPIC_BASE_URL for proxies.

    Returns:
        Tuple of (Anthropic client instance, model ID string).
    """
    load_dotenv(override=True)

    # Support custom base URL (e.g., for proxies)
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if base_url:
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

    api_key = _get_required_env("ANTHROPIC_API_KEY")
    model = os.getenv("MODEL_ID", DEFAULT_MODEL)

    client = Anthropic(
        api_key=api_key,
        base_url=base_url,
    )
    return client, model


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

def main() -> None:
    """Main entry point for the orbit CLI.

    Sets up all components:
    - Anthropic client
    - TodoManager (in-memory checklist)
    - TaskManager (file-based persistent tasks)
    - BackgroundManager (async command execution)
    - SkillLoader (SKILL.md knowledge files)
    - Compressor (conversation compression)
    - MessageBus (teammate communication)
    - TeammateManager (persistent agent lifecycle)

    Then runs the interactive REPL loop.
    """
    client, model = _setup_client()

    # Workspace root
    workdir = Path.cwd()

    # Directory paths
    team_dir = workdir / ".team"
    inbox_dir = team_dir / "inbox"
    tasks_dir = workdir / ".tasks"
    skills_dir = workdir / "skills"
    transcript_dir = workdir / ".transcripts"

    # ---- Initialize all components ----
    todo = TodoManager()
    task_mgr = TaskManager(tasks_dir)
    bg = BackgroundManager(workdir)
    skills = SkillLoader(skills_dir)
    compressor = Compressor(client, model, transcript_dir, TOKEN_THRESHOLD)
    bus = MessageBus(inbox_dir)
    team = TeammateManager(team_dir, bus, task_mgr, client, model, workdir)

    # Pre-bind subagent function with shared dependencies
    _run_subagent = partial(
        run_subagent,
        client=client,
        model=model,
        workdir=workdir,
    )

    # Build tool definitions and handlers
    tools = get_tools_for_lead()
    handlers = build_tool_handlers(
        todo=todo,
        task_mgr=task_mgr,
        bg=bg,
        skills=skills,
        compressor=compressor,
        team=team,
        bus=bus,
        workdir=workdir,
        run_subagent_fn=_run_subagent,
    )

    # Build system prompt
    system = build_system_prompt(workdir, skills)

    # ---- REPL header ----
    print(f"orbit v0.1.0 — workspace: {workdir}")
    print(f"Team: {team.config['team_name']}")
    print("Commands: /compact | /tasks | /team | /inbox | q/exit")
    print()

    # ---- REPL loop ----
    history: list[dict] = []

    while True:
        try:
            query = input("\033[36morbit >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = query.strip()

        # Quit
        if stripped.lower() in ("q", "exit", ""):
            break

        # REPL commands
        if stripped == "/compact":
            if history:
                print("[manual compact via /compact]")
                history[:] = compressor.auto_compact(history)
            continue
        if stripped == "/tasks":
            print(task_mgr.list_all())
            continue
        if stripped == "/team":
            print(team.list_all())
            continue
        if stripped == "/inbox":
            print(
                json.dumps(
                    bus.read_inbox("lead"),
                    indent=2,
                    ensure_ascii=False,
                )
            )
            continue

        # Normal turn
        history.append({"role": "user", "content": query})
        agent_loop(
            history,
            client=client,
            model=model,
            system=system,
            tools=tools,
            handlers=handlers,
            compressor=compressor,
            todo=todo,
            bg=bg,
            bus=bus,
        )

        # Print the assistant's final text response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()


if __name__ == "__main__":
    main()