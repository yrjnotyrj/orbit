#!/usr/bin/env python3
"""CLI entry point for orbit agent teams.

Usage:
    orbit              # Interactive CLI
    python -m orbit    # Run as module

Commands:
    /team    - List all teammates
    /inbox   - Read lead's inbox
    q, exit  - Quit
"""

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from .bus import MessageBus
from .core import agent_loop
from .manager import TeammateManager

# Environment variable defaults
DEFAULT_MODEL = "deepseek-v4-pro"


def _get_required_env(name: str) -> str:
    """Get a required environment variable, exiting with a clear message if missing.

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
        print(f"Please set {name} in your environment or .env file.", file=sys.stderr)
        sys.exit(1)
    return value


def _setup_client() -> tuple[Anthropic, str]:
    """Set up the Anthropic client from environment variables.

    Loads .env file, validates required variables, and creates the client.

    Returns:
        Tuple of (Anthropic client, model ID string).
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


def main() -> None:
    """Main entry point for the orbit CLI.

    Sets up the client, message bus, teammate manager, and runs the
    interactive agent loop. The .team/ directory is created in the
    current working directory, allowing orbit to run from any location.
    """
    client, model = _setup_client()

    # Use current working directory as the workspace root
    workdir = Path.cwd()
    team_dir = workdir / ".team"
    inbox_dir = team_dir / "inbox"

    bus = MessageBus(inbox_dir)
    team = TeammateManager(team_dir, bus, client, model)

    print(f"orbit v0.1.0 — workspace: {workdir}")
    print(f"Team: {team.config['team_name']}")
    print("Commands: /team | /inbox | q/exit")
    print()

    history: list[dict] = []
    while True:
        try:
            query = input("\033[36morbit >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = query.strip()

        if stripped.lower() in ("q", "exit", ""):
            break
        if stripped == "/team":
            print(team.list_all())
            continue
        if stripped == "/inbox":
            print(json.dumps(bus.read_inbox("lead"), indent=2, ensure_ascii=False))
            continue

        history.append({"role": "user", "content": query})
        agent_loop(history, client, model, bus, team, workdir)

        # Print the assistant's final text response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()


if __name__ == "__main__":
    main()
