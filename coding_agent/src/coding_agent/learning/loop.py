"""Post-task LLM learning reviewer orchestration."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import CoreHarness, HarnessResult, NullControlPlane
from core_harness.persistence import NullPersistence

from coding_agent.learning.prompts import REVIEWER_SYSTEM_PROMPT
from coding_agent.learning.sanitize import sanitize_task, sanitize_text
from coding_agent.learning.store import (
    LearningStore,
    ProposedLesson,
    TrustedLesson,
    default_expiry,
)
from coding_agent.learning.tools import build_reviewer_tools

logger = logging.getLogger(__name__)


class LearningLoop:
    """Optional LLM post-task reviewer; proposals stay separate from trusted lessons."""

    def __init__(
        self,
        store: LearningStore,
        *,
        registry: ModelRegistry,
        model_id: str,
        workspace: str,
        max_turns: int = 6,
    ) -> None:
        self.store = store
        self.registry = registry
        self.model_id = model_id
        self.workspace = workspace
        self.max_turns = max_turns

    async def after_task(
        self,
        task: str,
        result: HarnessResult,
        *,
        should_persist: bool = False,
        status: str = "completed",
        workspace_revision: str = "",
    ) -> Optional[HarnessResult]:
        """Run the LLM reviewer only when should_persist is true."""
        if not should_persist:
            return None

        tools, _read_ids = build_reviewer_tools(
            workspace=self.workspace,
            store=self.store,
            source_task=task,
            workspace_revision=workspace_revision,
        )
        harness = CoreHarness(
            registry=self.registry,
            model_id=self.model_id,
            system_prompt=REVIEWER_SYSTEM_PROMPT,
            tools=tools,
            control_plane=NullControlPlane(),
            persistence=NullPersistence(),
            max_turns=self.max_turns,
        )
        prompt = _reviewer_user_prompt(task=task, result=result, status=status)
        return await harness.run(prompt)

    def promote(
        self,
        *,
        summary: str,
        outcome: str,
        verification: str,
        evidence: str = "",
        workspace_revision: str = "",
        confidence: float = 0.8,
        proposed_id: Optional[str] = None,
    ) -> TrustedLesson:
        """Promote into the trusted playbook only with explicit verification."""
        if verification not in {"tests_passed", "user_approved", "evaluator"}:
            raise ValueError(
                "verification must be one of: tests_passed, user_approved, evaluator"
            )
        if outcome not in {"worked", "failed", "mixed", "note"}:
            raise ValueError("outcome must be one of: worked, failed, mixed, note")

        clean_summary = sanitize_text(summary, max_chars=240)
        clean_evidence = sanitize_text(
            evidence or f"proposed_id={proposed_id or 'n/a'}",
            max_chars=240,
        )
        content_hash = hashlib.sha256(
            f"{clean_summary}|{outcome}|{verification}|{workspace_revision}".encode("utf-8")
        ).hexdigest()[:16]
        lesson = TrustedLesson(
            id=str(uuid.uuid4()),
            summary=clean_summary,
            outcome=outcome,
            evidence=clean_evidence,
            verification=verification,
            workspace_revision=workspace_revision,
            confidence=max(0.0, min(1.0, confidence)),
            provenance="trusted_lesson",
            expires_at=default_expiry(),
            content_hash=content_hash,
            proposed_id=proposed_id,
        )
        self.store.append_trusted(lesson)
        return lesson

    def promote_proposed(
        self,
        proposed_id: str,
        *,
        verification: str,
        evidence: str = "",
    ) -> TrustedLesson:
        """Trust a previously proposed lesson after verification."""
        proposed = self.store.get_lesson(kind="proposed", lesson_id=proposed_id)
        if proposed is None or not isinstance(proposed, ProposedLesson):
            raise ValueError(f"proposed lesson not found: {proposed_id}")
        return self.promote(
            summary=proposed.summary,
            outcome=proposed.outcome,
            verification=verification,
            evidence=evidence or proposed.rationale,
            workspace_revision=proposed.workspace_revision,
            confidence=proposed.confidence,
            proposed_id=proposed.id,
        )


def _reviewer_user_prompt(*, task: str, result: HarnessResult, status: str) -> str:
    transcript = _compact_transcript(result)
    return (
        f"Task status: {status}\n"
        f"Task: {sanitize_task(task)}\n\n"
        f"Assistant output:\n{sanitize_text(result.output_text or '', max_chars=800)}\n\n"
        f"Transcript (sanitized, truncated):\n{transcript}\n\n"
        "If useful, propose lessons with the provided tools. "
        "Read any existing lesson fully before proposing an update."
    )


def _compact_transcript(result: HarnessResult, *, max_chars: int = 3000) -> str:
    lines: list[str] = []
    for message in result.messages:
        if message.role == "system":
            continue
        role = message.role
        content = message.content
        text = content if isinstance(content, str) else str(content)
        if message.role == "assistant" and message.tool_calls:
            names = []
            for call in message.tool_calls:
                if isinstance(call, dict):
                    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                    names.append(str(call.get("name") or fn.get("name") or "tool"))
            text = (text or "") + f" [tools: {', '.join(names)}]"
        lines.append(f"{role}: {sanitize_text(text, max_chars=240)}")
    blob = "\n".join(lines)
    if len(blob) > max_chars:
        return blob[: max_chars - 3].rstrip() + "..."
    return blob
