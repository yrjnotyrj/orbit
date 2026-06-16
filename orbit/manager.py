"""TeammateManager: persistent named agents with idle/claim lifecycle.

Manages the lifecycle of teammates — spawn, monitor, list, shutdown.
Each teammate runs in its own daemon thread with an agent loop
that alternates between working and idle phases.

    Teammate lifecycle:
    spawn -> working -> idle -> (auto-claim / message) -> working -> ...
                  |                |
                  +-- shutdown <---+

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

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anthropic import Anthropic

from .bus import MessageBus
from .task_mgr import TaskManager
from .tools import (
    _run_bash,
    _run_edit,
    _run_read,
    _run_write,
    get_tools_for_teammate,
)

# Timing constants
POLL_INTERVAL = 5       # seconds between idle polls
IDLE_TIMEOUT = 60       # seconds before idle teammate auto-shuts down


class TeammateManager:
    """Manages persistent named agents (teammates) with config.json state.

    Key insight: "Teammates that can talk to each other and self-organize."

    Each teammate:
    - Has a name, role, and status stored in .team/config.json
    - Runs in its own daemon thread
    - Communicates via the shared MessageBus
    - Has filesystem tools + messaging tools + idle/claim
    - Auto-claims unblocked pending tasks during idle phase
    """

    def __init__(
        self,
        team_dir: Path,
        bus: MessageBus,
        task_mgr: TaskManager,
        client: "Anthropic",
        model: str,
        workdir: Path,
    ) -> None:
        """Initialize the teammate manager.

        Args:
            team_dir: Path to the .team/ configuration directory.
            bus: MessageBus instance for teammate communication.
            task_mgr: TaskManager instance for task claiming.
            client: Anthropic API client.
            model: Model ID string.
            workdir: Workspace root directory.
        """
        self.dir = Path(team_dir)
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads: dict[str, threading.Thread] = {}
        self.bus = bus
        self.task_mgr = task_mgr
        self.client = client
        self.model = model
        self.workdir = workdir

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self) -> dict[str, Any]:
        """Load team configuration, or return defaults."""
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        """Persist current configuration to config.json."""
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _find_member(self, name: str) -> dict[str, Any] | None:
        """Find a team member by name."""
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _set_status(self, name: str, status: str) -> None:
        """Update a member's status and persist."""
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """Spawn a persistent teammate in its own daemon thread.

        If a teammate with the given name already exists and is
        idle or shutdown, it will be re-activated. If currently
        working, an error is returned.

        Args:
            name: Unique name for the teammate.
            role: Role description (e.g., "coder", "reviewer").
            prompt: Initial task prompt.

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

    def list_all(self) -> str:
        """List all teammates with name, role, and status.

        Returns:
            Formatted string showing team members.
        """
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list[str]:
        """Get the list of all teammate names."""
        return [m["name"] for m in self.config["members"]]

    # ------------------------------------------------------------------
    # Teammate agent loop
    # ------------------------------------------------------------------

    def _teammate_loop(self, name: str, role: str, prompt: str) -> None:
        """Run the full work/idle lifecycle for a teammate.

        Phases:
        1. WORK: call LLM with tools, execute tool calls (max 50 turns)
        2. IDLE: poll for inbox messages and unclaimed tasks
        3. If new work arrives → back to WORK
        4. If idle timeout expires → shutdown

        Args:
            name: Teammate's name.
            role: Teammate's role description.
            prompt: Initial task prompt.
        """
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, "
            f"at {self.workdir}. "
            f"Use idle when done with current work. "
            f"You may auto-claim tasks."
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": prompt},
        ]
        tools = get_tools_for_teammate()

        while True:
            # ====================================================
            # WORK PHASE
            # ====================================================
            for _ in range(50):
                # Inject any pending inbox messages
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
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
                    self._set_status(name, "shutdown")
                    return

                messages.append({
                    "role": "assistant",
                    "content": response.content,
                })

                if response.stop_reason != "tool_use":
                    break

                # Execute tool calls
                results: list[dict[str, Any]] = []
                idle_requested = False

                for block in response.content:
                    if block.type == "tool_use":
                        output = self._exec_tool(
                            name, block.name, block.input
                        )
                        if block.name == "idle":
                            idle_requested = True
                        print(
                            f"  [{name}] {block.name}: "
                            f"{str(output)[:120]}"
                        )
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output),
                        })

                messages.append({"role": "user", "content": results})

                if idle_requested:
                    break

            # ====================================================
            # IDLE PHASE
            # ====================================================
            self._set_status(name, "idle")
            resume = False

            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)

                # Check inbox for messages
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({
                            "role": "user",
                            "content": json.dumps(msg, ensure_ascii=False),
                        })
                    resume = True
                    break

                # Auto-claim unblocked pending tasks
                unclaimed = self.task_mgr.get_unclaimed()
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)

                    # Identity re-injection for compressed contexts
                    if len(messages) <= 3:
                        messages.insert(
                            0,
                            {
                                "role": "user",
                                "content": (
                                    f"<identity>You are '{name}', "
                                    f"role: {role}, team: {team_name}."
                                    f"</identity>"
                                ),
                            },
                        )
                        messages.insert(
                            1,
                            {
                                "role": "assistant",
                                "content": f"I am {name}. Continuing.",
                            },
                        )

                    messages.append({
                        "role": "user",
                        "content": (
                            f"<auto-claimed>"
                            f"Task #{task['id']}: {task['subject']}\n"
                            f"{task.get('description', '')}"
                            f"</auto-claimed>"
                        ),
                    })
                    messages.append({
                        "role": "assistant",
                        "content": (
                            f"Claimed task #{task['id']}. Working on it."
                        ),
                    })
                    resume = True
                    break

            if not resume:
                # Idle timeout — shut down
                self._set_status(name, "shutdown")
                return

            # Resume working
            self._set_status(name, "working")

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _exec_tool(
        self,
        sender: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> str:
        """Execute a tool call on behalf of a teammate.

        Args:
            sender: The teammate's name.
            tool_name: Name of the tool to execute.
            args: Tool input arguments.

        Returns:
            Tool execution result as a string.
        """
        if tool_name == "bash":
            return _run_bash(args["command"], self.workdir)
        if tool_name == "read_file":
            return _run_read(args["path"], self.workdir)
        if tool_name == "write_file":
            return _run_write(
                args["path"], args["content"], self.workdir
            )
        if tool_name == "edit_file":
            return _run_edit(
                args["path"],
                args["old_text"],
                args["new_text"],
                self.workdir,
            )
        if tool_name == "send_message":
            return self.bus.send(
                sender,
                args["to"],
                args["content"],
                args.get("msg_type", "message"),
            )
        if tool_name == "idle":
            return "Entering idle phase."
        if tool_name == "claim_task":
            return self.task_mgr.claim(args["task_id"], sender)
        return f"Unknown tool: {tool_name}"
