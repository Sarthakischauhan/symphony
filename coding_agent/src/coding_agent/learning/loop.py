"""Post-task learning loop: journal telemetry; promote only after verification."""

from __future__ import annotations

import hashlib
import uuid
from typing import Dict, List, Optional, Tuple

from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent.learning.sanitize import sanitize_task, sanitize_text
from coding_agent.learning.store import (
    LearningStore,
    Lesson,
    TaskJournalEntry,
    default_expiry,
)


class LearningLoop:
    """Record unverified task journals; promote verified lessons explicitly."""

    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def after_task(
        self,
        task: str,
        result: HarnessResult,
        *,
        status: str = "completed",
        workspace_revision: str = "",
    ) -> TaskJournalEntry:
        """Append raw telemetry only. Does not update the verified playbook."""
        tools_used, events = self._analyze(result)
        preview = sanitize_task(task)
        content_hash = hashlib.sha256(
            f"{preview}|{status}|{','.join(tools_used)}|{workspace_revision}".encode("utf-8")
        ).hexdigest()[:16]
        entry = TaskJournalEntry(
            id=str(uuid.uuid4()),
            task_preview=preview,
            status=status,
            tools_used=tools_used,
            tool_events=events,
            notes=f"status={status}; tools={len(tools_used)}; events={len(events)}",
            workspace_revision=workspace_revision,
            provenance="task_journal",
            confidence=0.0,
            verified=False,
            verification=None,
            expires_at=default_expiry(),
            content_hash=content_hash,
        )
        self.store.append_journal(entry)
        return entry

    def promote(
        self,
        *,
        summary: str,
        outcome: str,
        verification: str,
        evidence: str = "",
        workspace_revision: str = "",
        confidence: float = 0.8,
        tools_used: Optional[List[str]] = None,
        journal_id: Optional[str] = None,
    ) -> Lesson:
        """Promote a verified lesson into the playbook."""
        if verification not in {"tests_passed", "user_approved", "evaluator"}:
            raise ValueError(
                "verification must be one of: tests_passed, user_approved, evaluator"
            )
        if outcome not in {"worked", "failed", "mixed"}:
            raise ValueError("outcome must be one of: worked, failed, mixed")

        clean_summary = sanitize_text(summary, max_chars=240)
        clean_evidence = sanitize_text(evidence or f"journal_id={journal_id or 'n/a'}", max_chars=240)
        content_hash = hashlib.sha256(
            f"{clean_summary}|{outcome}|{verification}|{workspace_revision}".encode("utf-8")
        ).hexdigest()[:16]
        lesson = Lesson(
            id=str(uuid.uuid4()),
            summary=clean_summary,
            outcome=outcome,
            evidence=clean_evidence,
            verification=verification,
            workspace_revision=workspace_revision,
            confidence=max(0.0, min(1.0, confidence)),
            provenance="verified_lesson",
            expires_at=default_expiry(),
            content_hash=content_hash,
            tools_used=list(tools_used or []),
        )
        self.store.append_lesson(lesson)
        return lesson

    def _analyze(self, result: HarnessResult) -> Tuple[List[str], List[str]]:
        tool_names_by_id = _tool_names_by_id(result.messages)
        tools_used: list[str] = []
        events: list[str] = []

        for message in result.messages:
            if message.role != "tool":
                continue
            tool_id = message.tool_call_id or ""
            name = tool_names_by_id.get(tool_id, "tool")
            if name not in tools_used:
                tools_used.append(name)
            content = sanitize_text(_message_text(message), max_chars=160)
            kind = "error" if _looks_failed(content) else "ok"
            events.append(f"{name}:{kind}:{content}")

        return tools_used, events


def _tool_names_by_id(messages: List[Message]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for message in messages:
        if message.role != "assistant" or not message.tool_calls:
            continue
        for call in message.tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "")
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(call.get("name") or fn.get("name") or "tool")
            if call_id:
                names[call_id] = name
    return names


def _message_text(message: Message) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return str(content)


def _looks_failed(content: str) -> bool:
    text = content.strip()
    lowered = text.lower()
    if text.startswith("error:"):
        return True
    if text.startswith("exit=") and not text.startswith("exit=0"):
        return True
    if "traceback (most recent call last)" in lowered:
        return True
    return False
