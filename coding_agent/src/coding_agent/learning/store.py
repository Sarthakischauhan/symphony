"""Self-learning store under ``<workspace>/.symphony/learning``."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List


LEARNING_DIRNAME = "learning"
LESSONS_FILE = "lessons.jsonl"
PLAYBOOK_FILE = "playbook.md"
MAX_PLAYBOOK_ITEMS = 12


@dataclass
class Lesson:
    """One post-task learning record."""

    task: str
    outcome: str  # worked | mixed | failed
    worked: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    notes: str = ""
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class LearningStore:
    """Persist worked / failed patterns in ``.symphony/learning``."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".symphony" / LEARNING_DIRNAME
        self.lessons_path = self.root / LESSONS_FILE
        self.playbook_path = self.root / PLAYBOOK_FILE

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, lesson: Lesson) -> None:
        self.ensure()
        with self.lessons_path.open("a", encoding="utf-8") as handle:
            handle.write(lesson.to_json() + "\n")
        self.rebuild_playbook()

    def load_lessons(self, *, limit: int = 100) -> list[Lesson]:
        if not self.lessons_path.exists():
            return []
        lessons: list[Lesson] = []
        for line in self.lessons_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                lessons.append(
                    Lesson(
                        task=str(data.get("task", "")),
                        outcome=str(data.get("outcome", "mixed")),
                        worked=list(data.get("worked") or []),
                        failed=list(data.get("failed") or []),
                        tools_used=list(data.get("tools_used") or []),
                        notes=str(data.get("notes") or ""),
                        at=str(data.get("at") or ""),
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return lessons[-limit:]

    def rebuild_playbook(self) -> str:
        """Rewrite playbook.md from recent lessons (worked vs failed)."""
        self.ensure()
        lessons = self.load_lessons(limit=50)
        worked_tips = _unique_preserve(
            tip for lesson in lessons if lesson.outcome in {"worked", "mixed"} for tip in lesson.worked
        )
        failed_tips = _unique_preserve(
            tip for lesson in lessons if lesson.outcome in {"failed", "mixed"} for tip in lesson.failed
        )

        lines = [
            "# Symphony learning playbook",
            "",
            "Auto-updated after each coding-agent task from `.symphony/learning/lessons.jsonl`.",
            "",
            "## What worked",
        ]
        if worked_tips:
            for tip in worked_tips[-MAX_PLAYBOOK_ITEMS:]:
                lines.append(f"- {tip}")
        else:
            lines.append("- (none yet)")

        lines.extend(["", "## What did not work"])
        if failed_tips:
            for tip in failed_tips[-MAX_PLAYBOOK_ITEMS:]:
                lines.append(f"- {tip}")
        else:
            lines.append("- (none yet)")

        lines.extend(["", "## Recent tasks"])
        for lesson in lessons[-8:]:
            preview = lesson.task.strip().replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:117] + "..."
            lines.append(f"- [{lesson.outcome}] {preview}")

        text = "\n".join(lines) + "\n"
        self.playbook_path.write_text(text, encoding="utf-8")
        return text

    def playbook_context(self, *, max_chars: int = 2500) -> str:
        """Return playbook text for system-prompt injection."""
        if not self.playbook_path.exists():
            lessons = self.load_lessons(limit=1)
            if not lessons:
                return ""
            self.rebuild_playbook()
        text = self.playbook_path.read_text(encoding="utf-8").strip()
        if not text:
            return ""
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        return (
            "Lessons from prior tasks (self-learning playbook):\n"
            "Use these to avoid repeating failed approaches and prefer what worked.\n\n"
            f"{text}"
        )


def _unique_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = " ".join(str(item).split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out
