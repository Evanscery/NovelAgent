"""MessageStore — JSONL chat log persistence for the director chat API.

Extracted from chat.py to separate message persistence from route handling.
The chat log lives at ``work/chat.jsonl`` — one ChatMessage JSON object per line,
in chronological order, versioned by the project's independent git repo.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.api.schemas import ChatMessage

logger = logging.getLogger(__name__)

_CHAT_LOG_REL = Path("work") / "chat.jsonl"


class MessageStore:
    """Encapsulates JSONL chat log persistence for a single project."""

    def __init__(self, project_path: Path) -> None:
        self._project_path = project_path

    @property
    def project_path(self) -> Path:
        return self._project_path

    def chat_log_path(self) -> Path:
        """Return the chat log file path (``work/chat.jsonl``)."""
        return self._project_path / _CHAT_LOG_REL

    def ensure_log(self) -> Path:
        """Ensure the chat log file exists (create ``work/`` + empty file)."""
        log_path = self.chat_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.write_text("", encoding="utf-8")
        return log_path

    def read_messages(self) -> list[ChatMessage]:
        """Read every line of the chat log into ChatMessage objects.

        Malformed lines are skipped (a corrupted log must not crash the read).
        """
        log_path = self.chat_log_path()
        if not log_path.exists():
            return []
        messages: list[ChatMessage] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("chat log: skipping malformed line: %r", line[:80])
                continue
            try:
                messages.append(ChatMessage.model_validate(obj))
            except Exception:  # noqa: BLE001 — skip semantically invalid entries
                logger.warning("chat log: skipping invalid message: %r", line[:80])
                continue
        return messages

    def append_message(self, message: ChatMessage) -> None:
        """Append a single ChatMessage as one JSONL line."""
        log_path = self.chat_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(message.model_dump_json() + "\n")
