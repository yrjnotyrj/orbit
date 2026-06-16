"""Compressor: conversation context compression.

Provides:
- estimate_tokens: rough token count estimation
- microcompact: clear old tool results to save space
- auto_compact: summarize conversation and reset to a compact state

Used by the agent loop to stay within context windows.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import Anthropic


class Compressor:
    """Manages conversation compression for the agent loop.

    Microcompact runs every turn and clears tool results older than
    the most recent 3. Auto-compact triggers when estimated tokens
    exceed a threshold — it saves the transcript and produces a
    summary to restart the conversation.
    """

    def __init__(
        self,
        client: "Anthropic",
        model: str,
        transcript_dir: Path,
        token_threshold: int = 100000,
    ) -> None:
        """Initialize the compressor.

        Args:
            client: Anthropic API client for summary generation.
            model: Model ID for summary calls.
            transcript_dir: Directory for saving full transcripts.
            token_threshold: Token count that triggers auto-compact.
        """
        self.client = client
        self.model = model
        self.dir = Path(transcript_dir)
        self.threshold = token_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """Rough token estimation: JSON byte length / 4.

        Args:
            messages: List of message dicts.

        Returns:
            Estimated token count.
        """
        return len(json.dumps(messages, default=str)) // 4

    @staticmethod
    def microcompact(messages: list[dict]) -> None:
        """Clear old tool result contents, keeping only the 3 most recent.

        Tool results older than the 3rd-from-last are replaced with
        '[cleared]' to save context space. Messages with <= 100 chars
        are left untouched.

        Args:
            messages: Message list (mutated in place).
        """
        # Collect all tool_result parts across all user messages
        parts: list[dict] = []
        for msg in messages:
            if msg["role"] == "user" and isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        parts.append(part)

        if len(parts) <= 3:
            return

        # Clear all but the 3 most recent
        for part in parts[:-3]:
            if isinstance(part.get("content"), str) and len(part["content"]) > 100:
                part["content"] = "[cleared]"

    def auto_compact(self, messages: list[dict]) -> list[dict]:
        """Save transcript and produce a compressed summary.

        Writes the full conversation to a timestamped JSONL file,
        then asks the model to summarize the last ~80k chars for
        continuity. Returns a new message list containing only the
        summary.

        Args:
            messages: Current message history.

        Returns:
            New message list: [summary_message].
        """
        self.dir.mkdir(exist_ok=True)
        timestamp = int(time.time())
        path = self.dir / f"transcript_{timestamp}.jsonl"

        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str) + "\n")

        # Summarize the tail of the conversation
        conv_text = json.dumps(messages, default=str)[-80000:]
        resp = self.client.messages.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": f"Summarize for continuity:\n{conv_text}",
            }],
            max_tokens=2000,
        )
        summary = resp.content[0].text

        return [
            {
                "role": "user",
                "content": (
                    f"[Compressed. Transcript: {path}]\n{summary}"
                ),
            },
        ]
