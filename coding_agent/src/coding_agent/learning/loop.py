"""Post-task self-learning loop: derive what worked / failed and persist it."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core_ai.types import Message
from core_harness import HarnessResult

from coding_agent.learning.store import LearningStore, Lesson


class LearningLoop:
    """Analyze a completed harness run and update ``.symphony/learning``."""

    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def after_task(self, task: str, result: HarnessResult) -> Lesson:
        worked, failed, tools_used = self._analyze(result)
        if failed and not worked:
            outcome = "failed"
        elif worked and not failed:
            outcome = "worked"
        else:
            outcome = "mixed"

        notes = self._notes(outcome, worked, failed, result)
        lesson = Lesson(
            task=task,
            outcome=outcome,
            worked=worked,
            failed=failed,
            tools_used=tools_used,
            notes=notes,
        )
        self.store.append(lesson)
        return lesson

    def _analyze(
        self, result: HarnessResult
    ) -> Tuple[List[str], List[str], List[str]]:
        tool_names_by_id = _tool_names_by_id(result.messages)
        worked: list[str] = []
        failed: list[str] = []
        tools_used: list[str] = []

        for message in result.messages:
            if message.role != "tool":
                continue
            tool_id = message.tool_call_id or ""
            name = tool_names_by_id.get(tool_id, "tool")
            if name not in tools_used:
                tools_used.append(name)
            content = _message_text(message)
            tip = _lesson_from_tool(name, content)
            if _looks_failed(content):
                failed.append(tip)
            else:
                worked.append(tip)

        if not tools_used and result.output_text.strip():
            worked.append("Completed task without tools (direct answer)")

        return _dedupe(worked), _dedupe(failed), tools_used

    def _notes(
        self,
        outcome: str,
        worked: List[str],
        failed: List[str],
        result: HarnessResult,
    ) -> str:
        parts = [f"outcome={outcome}"]
        if result.usage and result.usage.total_tokens:
            parts.append(f"tokens={result.usage.total_tokens}")
        parts.append(f"worked={len(worked)}")
        parts.append(f"failed={len(failed)}")
        return "; ".join(parts)


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
    if "old_str not found" in lowered or "matched" in lowered and "times" in lowered:
        return True
    return False


def _lesson_from_tool(name: str, content: str) -> str:
    preview = " ".join(content.strip().split())
    if len(preview) > 160:
        preview = preview[:157] + "..."
    if _looks_failed(content):
        return f"{name} failed: {preview}"
    if name == "patch" and preview.startswith("patched "):
        return f"patch succeeded ({preview})"
    if name == "bash" and not preview.startswith("exit="):
        return f"bash succeeded: {preview[:80]}"
    if name == "write_file" and preview.startswith("wrote "):
        return f"write_file succeeded ({preview})"
    if name == "ast_query":
        return f"ast_query useful: {preview[:80]}"
    return f"{name}: {preview[:100]}"


def _dedupe(items: List[str]) -> List[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
