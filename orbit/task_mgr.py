"""TaskManager: file-based persistent task tracking.

Tasks are stored as individual JSON files in a .tasks/ directory.
Each task has an auto-incrementing ID, subject, description, status,
owner, and blockedBy list. Supports CRUD operations plus claiming.
"""

from __future__ import annotations

import json
from pathlib import Path


class TaskManager:
    """Persistent file-based task manager.

    Tasks live as task_<id>.json files under the tasks directory.
    This allows tasks to survive agent restarts and be shared
    across teammates.

        .tasks/
        +------------------+
        | task_1.json      |
        | task_2.json      |
        +------------------+
    """

    def __init__(self, tasks_dir: Path) -> None:
        """Initialize the task manager.

        Args:
            tasks_dir: Path to the .tasks/ directory.
        """
        self.dir = Path(tasks_dir)
        self.dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        """Determine the next available task ID.

        Returns:
            One greater than the highest existing task ID, or 1 if no tasks.
        """
        ids = [
            int(f.stem.split("_")[1])
            for f in self.dir.glob("task_*.json")
        ]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        """Load a task by ID.

        Args:
            tid: Task ID.

        Returns:
            Task dictionary.

        Raises:
            ValueError: If the task file does not exist.
        """
        path = self.dir / f"task_{tid}.json"
        if not path.exists():
            raise ValueError(f"Task {tid} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, task: dict) -> None:
        """Persist a task to its JSON file.

        Args:
            task: Task dictionary (must contain 'id' key).
        """
        path = self.dir / f"task_{task['id']}.json"
        path.write_text(
            json.dumps(task, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, subject: str, description: str = "") -> str:
        """Create a new pending task.

        Args:
            subject: Short task title.
            description: Optional longer description.

        Returns:
            JSON string of the created task.
        """
        task: dict = {
            "id": self._next_id(),
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": None,
            "blockedBy": [],
        }
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def get(self, tid: int) -> str:
        """Get a task's full details by ID.

        Args:
            tid: Task ID.

        Returns:
            JSON string of the task.
        """
        return json.dumps(self._load(tid), indent=2, ensure_ascii=False)

    def update(
        self,
        tid: int,
        status: str | None = None,
        add_blocked_by: list[int] | None = None,
        remove_blocked_by: list[int] | None = None,
    ) -> str:
        """Update a task's status and/or dependency links.

        When a task is completed, it is removed from the blockedBy
        lists of all other tasks. When deleted, its JSON file is removed.

        Args:
            tid: Task ID.
            status: New status (pending, in_progress, completed, deleted).
            add_blocked_by: Task IDs to add as blockers.
            remove_blocked_by: Task IDs to remove as blockers.

        Returns:
            JSON string of the updated task, or a deletion message.
        """
        task = self._load(tid)

        if status is not None:
            task["status"] = status
            if status == "completed":
                # Unblock any tasks that were waiting on this one
                for f in self.dir.glob("task_*.json"):
                    t = json.loads(f.read_text(encoding="utf-8"))
                    if tid in t.get("blockedBy", []):
                        t["blockedBy"].remove(tid)
                        self._save(t)
            if status == "deleted":
                (self.dir / f"task_{tid}.json").unlink(missing_ok=True)
                return f"Task {tid} deleted"

        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [
                x for x in task["blockedBy"] if x not in remove_blocked_by
            ]

        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def list_all(self) -> str:
        """List all tasks with status markers.

        Returns:
            Human-readable task list, or 'No tasks.' if empty.
        """
        tasks = [
            json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(self.dir.glob("task_*.json"))
        ]
        if not tasks:
            return "No tasks."

        markers = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
        }
        lines: list[str] = []
        for t in tasks:
            marker = markers.get(t["status"], "[?]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{blocked}")

        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        """Claim a task for a specific owner.

        Sets the task's owner and moves it to in_progress.

        Args:
            tid: Task ID to claim.
            owner: Name of the claiming agent/teammate.

        Returns:
            Status message describing the claim.
        """
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{tid} for {owner}"

    def get_unclaimed(self) -> list[dict]:
        """Get all pending, unblocked, unowned tasks.

        Returns:
            List of task dictionaries ready for claiming.
        """
        unclaimed: list[dict] = []
        for f in sorted(self.dir.glob("task_*.json")):
            t = json.loads(f.read_text(encoding="utf-8"))
            if (
                t.get("status") == "pending"
                and not t.get("owner")
                and not t.get("blockedBy")
            ):
                unclaimed.append(t)
        return unclaimed
