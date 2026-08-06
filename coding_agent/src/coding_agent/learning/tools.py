"""Tools used by the post-task LLM learning reviewer."""

from __future__ import annotations

import hashlib
import uuid
from typing import Set

from pydantic import Field

from coding_agent.learning.sanitize import sanitize_task, sanitize_text
from coding_agent.learning.store import (
    LearningStore,
    ProposedLesson,
    default_expiry,
)
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class ListLessonsArgs(ToolArgsModel):
    kind: str = Field(
        default="proposed",
        description="Which store to list: 'proposed' or 'trusted'.",
    )


class ReadLessonArgs(ToolArgsModel):
    kind: str = Field(..., description="'proposed' or 'trusted'.")
    lesson_id: str = Field(..., min_length=1, description="Lesson id to read in full.")


class ProposeLessonArgs(ToolArgsModel):
    summary: str = Field(..., min_length=1, description="Short lesson summary.")
    outcome: str = Field(
        default="note",
        description="worked | failed | mixed | note",
    )
    rationale: str = Field(
        default="",
        description="Why this lesson is useful given the completed task.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ProposeUpdateArgs(ToolArgsModel):
    kind: str = Field(..., description="Store of the lesson being updated: proposed|trusted.")
    lesson_id: str = Field(..., min_length=1, description="Id of the existing lesson.")
    summary: str = Field(..., min_length=1, description="Updated lesson summary.")
    outcome: str = Field(default="note", description="worked | failed | mixed | note")
    rationale: str = Field(
        default="",
        description="Why the update is needed after reading the full current lesson.",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class _ReviewerToolBase(WorkspaceTool):
    """Shared workspace root for reviewer tools (unused for FS; store-backed)."""

    def __init__(
        self,
        workspace: str,
        *,
        store: LearningStore,
        read_ids: Set[str],
        source_task: str,
        workspace_revision: str,
    ) -> None:
        super().__init__(workspace)
        self.store = store
        self.read_ids = read_ids
        self.source_task = source_task
        self.workspace_revision = workspace_revision


class ListLessonsTool(_ReviewerToolBase):
    name = "list_lessons"
    description = (
        "List proposed or trusted lessons (id + short summary only). "
        "Call read_lesson before proposing an update to any existing lesson."
    )
    args_model = ListLessonsArgs

    def run(self, kind: str = "proposed") -> str:
        kind = kind.strip().lower()
        if kind not in {"proposed", "trusted"}:
            return "error: kind must be 'proposed' or 'trusted'"
        lessons = (
            self.store.load_proposed(limit=50)
            if kind == "proposed"
            else self.store.load_trusted(limit=50)
        )
        if not lessons:
            return f"no {kind} lessons"
        lines = [f"{len(lessons)} {kind} lesson(s):"]
        for lesson in lessons:
            lines.append(f"- {lesson.id}: {sanitize_text(lesson.summary, max_chars=120)}")
        return "\n".join(lines)


class ReadLessonTool(_ReviewerToolBase):
    name = "read_lesson"
    description = (
        "Read the complete current contents of one lesson. "
        "Required before propose_update for that lesson_id."
    )
    args_model = ReadLessonArgs

    def run(self, kind: str, lesson_id: str) -> str:
        kind = kind.strip().lower()
        lesson = self.store.get_lesson(kind=kind, lesson_id=lesson_id)
        if lesson is None:
            return f"error: lesson not found: {kind}/{lesson_id}"
        key = f"{kind}:{lesson_id}"
        self.read_ids.add(key)
        return self.store.render_lesson(lesson)


class ProposeLessonTool(_ReviewerToolBase):
    name = "propose_lesson"
    description = (
        "Append a NEW proposed lesson. Does not modify trusted lessons. "
        "Use propose_update to suggest changes to an existing lesson after reading it."
    )
    args_model = ProposeLessonArgs

    def run(
        self,
        summary: str,
        outcome: str = "note",
        rationale: str = "",
        confidence: float = 0.5,
    ) -> str:
        outcome = outcome.strip().lower() or "note"
        if outcome not in {"worked", "failed", "mixed", "note"}:
            return "error: outcome must be worked|failed|mixed|note"
        clean_summary = sanitize_text(summary, max_chars=240)
        clean_rationale = sanitize_text(rationale, max_chars=400)
        content_hash = hashlib.sha256(
            f"{clean_summary}|{outcome}|{self.workspace_revision}".encode("utf-8")
        ).hexdigest()[:16]
        lesson = ProposedLesson(
            id=str(uuid.uuid4()),
            summary=clean_summary,
            outcome=outcome,
            rationale=clean_rationale,
            source_task=sanitize_task(self.source_task),
            workspace_revision=self.workspace_revision,
            confidence=max(0.0, min(1.0, confidence)),
            expires_at=default_expiry(),
            content_hash=content_hash,
        )
        self.store.append_proposed(lesson)
        return f"proposed lesson {lesson.id}"


class ProposeUpdateTool(_ReviewerToolBase):
    name = "propose_update"
    description = (
        "Propose an update to an existing lesson AFTER read_lesson on that id. "
        "Writes a new proposed entry that references the prior lesson; "
        "never rewrites trusted lessons in place."
    )
    args_model = ProposeUpdateArgs

    def run(
        self,
        kind: str,
        lesson_id: str,
        summary: str,
        outcome: str = "note",
        rationale: str = "",
        confidence: float = 0.5,
    ) -> str:
        kind = kind.strip().lower()
        if kind not in {"proposed", "trusted"}:
            return "error: kind must be 'proposed' or 'trusted'"
        key = f"{kind}:{lesson_id}"
        if key not in self.read_ids:
            return (
                "error: read the complete current lesson with read_lesson "
                f"({kind}, {lesson_id}) before proposing an update"
            )
        current = self.store.get_lesson(kind=kind, lesson_id=lesson_id)
        if current is None:
            return f"error: lesson not found: {kind}/{lesson_id}"

        outcome = outcome.strip().lower() or "note"
        if outcome not in {"worked", "failed", "mixed", "note"}:
            return "error: outcome must be worked|failed|mixed|note"

        clean_summary = sanitize_text(summary, max_chars=240)
        clean_rationale = sanitize_text(rationale, max_chars=400)
        prior_summary = sanitize_text(current.summary, max_chars=240)
        content_hash = hashlib.sha256(
            f"update|{lesson_id}|{clean_summary}|{outcome}|{self.workspace_revision}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        lesson = ProposedLesson(
            id=str(uuid.uuid4()),
            summary=clean_summary,
            outcome=outcome,
            rationale=clean_rationale,
            source_task=sanitize_task(self.source_task),
            workspace_revision=self.workspace_revision,
            confidence=max(0.0, min(1.0, confidence)),
            expires_at=default_expiry(),
            content_hash=content_hash,
            replaces_id=lesson_id,
            replaces_kind=kind,
            prior_summary=prior_summary,
        )
        self.store.append_proposed(lesson)
        return f"proposed update {lesson.id} (replaces {kind}/{lesson_id})"


def build_reviewer_tools(
    *,
    workspace: str,
    store: LearningStore,
    source_task: str,
    workspace_revision: str,
) -> tuple[list, Set[str]]:
    """Create reviewer tools sharing a per-run read-tracking set."""
    from core_harness import Tool

    read_ids: Set[str] = set()
    instances = [
        ListLessonsTool(
            workspace,
            store=store,
            read_ids=read_ids,
            source_task=source_task,
            workspace_revision=workspace_revision,
        ),
        ReadLessonTool(
            workspace,
            store=store,
            read_ids=read_ids,
            source_task=source_task,
            workspace_revision=workspace_revision,
        ),
        ProposeLessonTool(
            workspace,
            store=store,
            read_ids=read_ids,
            source_task=source_task,
            workspace_revision=workspace_revision,
        ),
        ProposeUpdateTool(
            workspace,
            store=store,
            read_ids=read_ids,
            source_task=source_task,
            workspace_revision=workspace_revision,
        ),
    ]
    return [inst.as_harness_tool() for inst in instances], read_ids
