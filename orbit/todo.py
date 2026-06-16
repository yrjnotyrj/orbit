"""TodoManager: in-memory task tracking list for the agent.

Provides the TodoWrite tool handler — a lightweight checklist that the
model uses to track short-term subtasks. Enforces:
- Max 20 items
- Only one item in_progress at a time
- Every item requires content, status, and activeForm
"""

from __future__ import annotations


class TodoManager:
    """In-memory task checklist for the agent loop.

    The model calls TodoWrite to update this list. It is displayed
    back to the model on each update. A nag reminder is injected if
    there are open items and the model hasn't updated the list for
    3 consecutive rounds.
    """

    def __init__(self) -> None:
        self.items: list[dict] = []

    def update(self, items: list[dict]) -> str:
        """Validate and replace the todo list.

        Args:
            items: List of dicts with keys: content, status, activeForm.

        Returns:
            Rendered todo list string.

        Raises:
            ValueError: If validation fails (missing fields, invalid status,
                        too many items, or multiple in_progress).
        """
        validated: list[dict] = []
        in_progress_count = 0

        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()

            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                in_progress_count += 1

            validated.append({
                "content": content,
                "status": status,
                "activeForm": active_form,
            })

        if len(validated) > 20:
            raise ValueError("Max 20 todos")
        if in_progress_count > 1:
            raise ValueError("Only one in_progress allowed")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """Render the current todo list as a readable string.

        Returns:
            Formatted todo list with status markers and completion count.
        """
        if not self.items:
            return "No todos."

        markers = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
        }
        lines: list[str] = []
        for item in self.items:
            marker = markers.get(item["status"], "[?]")
            suffix = ""
            if item["status"] == "in_progress":
                suffix = f" <- {item['activeForm']}"
            lines.append(f"{marker} {item['content']}{suffix}")

        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        """Check whether any items are not yet completed.

        Returns:
            True if at least one item has status != 'completed'.
        """
        return any(item.get("status") != "completed" for item in self.items)
