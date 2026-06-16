"""TeammateManager: persistent named agents with config.json.

Manages the lifecycle of teammates — spawn, monitor, list, shutdown.
Each teammate runs in its own daemon thread with an agent loop.

    Subagent:  spawn -> execute -> return summary -> destroyed
    Teammate:  spawn -> work -> idle -> work -> ... -> shutdown

    .team/config.json                   .team/inbox/
    +----------------------------+      +------------------+
    | {"team_name": "default",   |      | alice.jsonl      |
    |  "members": [              |      | bob.jsonl        |
    |    {"name":"alice",        |      | lead.jsonl       |
    |     "role":"coder",        |      +------------------+
    |     "status":"idle"}       |
    |  ]}                        |
    +----------------------------+
"""

import json
import threading
from pathlib import Path
from typing import Any, Optional

from anthropic import Anthropic

from .bus import MessageBus
from .tools import (
    _run_bash,
    _run_edit,
    _run_read,
    _run_write,
    get_tools_for_teammate,
)


class TeammateManager:
    """Manages persistent named agents (teammates) with config.json state.

    Key insight: "Teammates that can talk to each other."

    Each teammate:
    - Has a name, role, and status stored in .team/config.json
    - Runs in its own daemon thread
    - Communicates via the shared MessageBus
    - Has filesystem tools + messaging tools
    """

    def __init__(
        self,
        team_dir: Path,
        bus: MessageBus,
        client: Anthropic,
        model: str,
    ):
        """Initialize the teammate manager.

        Args:
            team_dir: Path to the .team/ configuration directory.
            bus: MessageBus instance for teammate communication.
            client: Anthropic API client.
            model: Model ID string.
        """
        self.dir = Path(team_dir)
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads: dict[str, threading.Thread] = {}
        self.bus = bus
        self.client = client
        self.model = model

    def _load_config(self) -> dict[str, Any]:
        """Load team configuration from config.json, or return defaults."""
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        """Persist current team configuration to config.json."""
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _find_member(self, name: str) -> Optional[dict[str, Any]]:
        """Find a team member by name.

        Args:
            name: The teammate's name.

        Returns:
            Member dictionary if found, None otherwise.
        """
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """Spawn a persistent teammate in its own daemon thread.

        If a teammate with the given name already exists and is idle/shutdown,
        it will be re-activated. If it's currently working, an error is returned.

        Args:
            name: Unique name for the teammate.
            role: Role description (e.g., "coder", "reviewer").
            prompt: Initial task prompt for the teammate.

        Returns:
            Status string describing the result.
        """
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()
        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"

    def _exec(self, sender: str, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tool call on behalf of a teammate.

        Args:
            sender: The teammate's name.
            tool_name: Name of the tool to execute.
            args: Tool input arguments.

        Returns:
            Tool execution result as a string.
        """
        workdir = Path.cwd()
        if tool_name == "bash":
            return _run_bash(args["command"], workdir)
        if tool_name == "read_file":
            return _run_read(args["path"], workdir)
        if tool_name == "write_file":
            return _run_write(args["path"], args["content"], workdir)
        if tool_name == "edit_file":
            return _run_edit(args["path"], args["old_text"], args["new_text"], workdir)
        if tool_name == "send_message":
            return self.bus.send(
                sender,
                args["to"],
                args["content"],
                args.get("msg_type", "message"),
            )
        if tool_name == "read_inbox":
            return json.dumps(
                self.bus.read_inbox(sender), indent=2, ensure_ascii=False
            )
        return f"Unknown tool: {tool_name}"

    def _teammate_loop(self, name: str, role: str, prompt: str) -> None:
        """Run the agent loop for a teammate in a separate thread.

        The teammate:
        1. Reads its inbox for new messages
        2. Calls the LLM with tools
        3. Executes any tool calls
        4. Repeats until stop_reason is not tool_use or max iterations (50)

        Status is set back to 'idle' when the loop completes.

        Args:
            name: Teammate's name.
            role: Teammate's role description.
            prompt: Initial task prompt.
        """
        workdir = Path.cwd()
        sys_prompt = (
            f"You are '{name}', role: {role}, at {workdir}. "
            f"Use send_message to communicate. Complete your task."
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tools = get_tools_for_teammate()

        for _ in range(50):
            # Read and inject any new inbox messages
            inbox = self.bus.read_inbox(name)
            for msg in inbox:
                messages.append({
                    "role": "user",
                    "content": json.dumps(msg, ensure_ascii=False),
                })

            try:
                response = self.client.messages.create(
                    model=self.model,
                    system=sys_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=8000,
                )
            except Exception:
                break

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            # Execute tool calls
            results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "tool_use":
                    output = self._exec(name, block.name, block.input)
                    print(f"  [{name}] {block.name}: {str(output)[:120]}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    })
            messages.append({"role": "user", "content": results})

        # Mark as idle when done (unless shutdown was requested)
        member = self._find_member(name)
        if member and member["status"] != "shutdown":
            member["status"] = "idle"
            self._save_config()

    def list_all(self) -> str:
        """List all teammates with their name, role, and status.

        Returns:
            Formatted string showing team name and member list.
        """
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list[str]:
        """Get the list of all teammate names.

        Returns:
            List of teammate name strings.
        """
        return [m["name"] for m in self.config["members"]]
