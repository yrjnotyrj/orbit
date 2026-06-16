"""MessageBus: JSONL inbox per teammate.

Each teammate has a .jsonl file in the inbox directory.
Messages are appended by senders and drained by the recipient.
"""

import json
import time
from pathlib import Path
from typing import Any, Optional

# Valid message types (all declared, not all handled in s09)
VALID_MSG_TYPES = {
    "message",               # Normal text message
    "broadcast",             # Sent to all teammates
    "shutdown_request",      # Request graceful shutdown (s10)
    "shutdown_response",     # Approve/reject shutdown (s10)
    "plan_approval_response",# Approve/reject plan (s10)
}


class MessageBus:
    """File-based JSONL inbox system for teammate communication.

        .team/inbox/
        +------------------+
        | alice.jsonl      |
        | bob.jsonl        |
        | lead.jsonl       |
        +------------------+

        send_message("alice", "fix bug"):
          open("alice.jsonl", "a").write(msg)

        read_inbox("alice"):
          msgs = [json.loads(l) for l in ...]
          open("alice.jsonl", "w").close()
          return msgs  # drain
    """

    def __init__(self, inbox_dir: Path):
        """Initialize the message bus with an inbox directory.

        Args:
            inbox_dir: Path to the directory containing per-teammate .jsonl inbox files.
        """
        self.dir = Path(inbox_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: Optional[dict] = None,
    ) -> str:
        """Send a message to a teammate's inbox.

        Args:
            sender: Name of the sender.
            to: Name of the recipient teammate.
            content: Message content.
            msg_type: Type of message (must be in VALID_MSG_TYPES).
            extra: Optional extra fields to add to the message.

        Returns:
            Status string describing the result.
        """
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        msg: dict[str, Any] = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list[dict[str, Any]]:
        """Read and drain a teammate's inbox.

        Reads all messages from the inbox file, then clears it (drain semantics).

        Args:
            name: Name of the teammate whose inbox to read.

        Returns:
            List of message dictionaries (empty if no messages).
        """
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []
        messages: list[dict[str, Any]] = []
        text = inbox_path.read_text(encoding="utf-8").strip()
        if text:
            for line in text.splitlines():
                if line.strip():
                    messages.append(json.loads(line))
            inbox_path.write_text("")
        return messages

    def broadcast(self, sender: str, content: str, teammates: list[str]) -> str:
        """Send a broadcast message to all teammates except the sender.

        Args:
            sender: Name of the sender (excluded from recipients).
            content: Message content.
            teammates: List of all teammate names.

        Returns:
            Status string with count of recipients.
        """
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"
