"""BackgroundManager: run shell commands in background threads.

Commands are executed asynchronously. Results are collected via a
thread-safe queue and can be drained by the agent loop for injection
as <background-results> messages.
"""

from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path
from queue import Queue


class BackgroundManager:
    """Run shell commands in daemon threads with result notifications.

    The agent can launch long-running commands without blocking the
    main loop. Completed results are queued and injected into the
    conversation on the next agent loop iteration.

        background_run("pytest") -> starts thread -> queues result
        check_background(task_id) -> poll a specific task
        drain() -> collect all pending notifications
    """

    def __init__(self, workdir: Path) -> None:
        """Initialize the background manager.

        Args:
            workdir: Working directory for command execution.
        """
        self.workdir = Path(workdir)
        self.tasks: dict[str, dict] = {}
        self.notifications: Queue = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        """Launch a command in a background daemon thread.

        Args:
            command: Shell command to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            Status message with the assigned task ID.
        """
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {
            "status": "running",
            "command": command,
            "result": None,
        }
        thread = threading.Thread(
            target=self._exec,
            args=(tid, command, timeout),
            daemon=True,
        )
        thread.start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int) -> None:
        """Internal: execute the command and queue the result.

        Args:
            tid: Task ID.
            command: Shell command.
            timeout: Max execution seconds.
        """
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[tid].update({
                "status": "completed",
                "result": output or "(no output)",
            })
        except subprocess.TimeoutExpired:
            self.tasks[tid].update({
                "status": "error",
                "result": f"Timeout after {timeout}s",
            })
        except Exception as e:
            self.tasks[tid].update({
                "status": "error",
                "result": str(e),
            })

        # Queue notification for the agent loop
        self.notifications.put({
            "task_id": tid,
            "status": self.tasks[tid]["status"],
            "result": (self.tasks[tid]["result"] or "")[:500],
        })

    def check(self, tid: str | None = None) -> str:
        """Check the status of background tasks.

        Args:
            tid: Specific task ID to check, or None for all tasks.

        Returns:
            Status string for the requested task(s).
        """
        if tid:
            t = self.tasks.get(tid)
            if t:
                return f"[{t['status']}] {t.get('result') or '(running)'}"
            return f"Unknown task: {tid}"

        if not self.tasks:
            return "No background tasks."

        lines: list[str] = []
        for k, v in self.tasks.items():
            lines.append(f"{k}: [{v['status']}] {v['command'][:60]}")
        return "\n".join(lines)

    def drain(self) -> list[dict]:
        """Collect all pending background notifications.

        Drains the notification queue and returns all pending
        results. Called by the agent loop before each LLM call.

        Returns:
            List of notification dicts with task_id, status, result.
        """
        notifs: list[dict] = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs
