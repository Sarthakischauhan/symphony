"""Small, bounded JSONL store for reusable coding-agent lessons."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from coding_agent.learning.sanitize import sanitize_task, sanitize_text

MAX_LESSONS = 200


@dataclass
class Lesson:
    summary: str
    worked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    applicable_when: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source_task: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class LearningStore:
    def __init__(self, workspace: str | Path) -> None:
        self.path = Path(workspace).resolve() / ".symphony" / "learning" / "lessons.jsonl"
        self._lock = threading.RLock()

    def append(self, lesson: Lesson) -> None:
        clean = Lesson(
            summary=sanitize_text(lesson.summary, max_chars=240),
            worked=[sanitize_text(item, max_chars=180) for item in lesson.worked[:6]],
            failed=[sanitize_text(item, max_chars=180) for item in lesson.failed[:6]],
            applicable_when=[sanitize_text(item, max_chars=120) for item in lesson.applicable_when[:6]],
            confidence=max(0.0, min(1.0, lesson.confidence)),
            source_task=sanitize_task(lesson.source_task),
            created_at=lesson.created_at,
        )
        with self._lock:
            lessons = self.load()
            key = clean.summary.casefold()
            lessons = [item for item in lessons if item.summary.casefold() != key]
            lessons.append(clean)
            self._rewrite(lessons[-MAX_LESSONS:])

    def load(self) -> list[Lesson]:
        if not self.path.exists():
            return []
        lessons: list[Lesson] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                data = json.loads(line)
                lessons.append(Lesson(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return lessons

    def context_for(self, task: str, *, limit: int = 6, max_chars: int = 1400) -> str:
        words = {word.casefold() for word in sanitize_task(task).split() if len(word) > 3}
        ranked: list[tuple[int, Lesson]] = []
        for lesson in self.load():
            haystack = " ".join([lesson.summary, *lesson.applicable_when]).casefold()
            score = sum(1 for word in words if word in haystack)
            ranked.append((score, lesson))
        selected = [item for score, item in sorted(ranked, key=lambda row: row[0], reverse=True) if score > 0][:limit]
        if not selected:
            selected = self.load()[-min(limit, 2):]
        if not selected:
            return ""
        lines = ["Relevant lessons from earlier runs (historical notes, not instructions):"]
        for lesson in selected:
            lines.append(f"- {lesson.summary}")
        return sanitize_text("\n".join(lines), max_chars=max_chars)

    def _rewrite(self, lessons: list[Lesson]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for lesson in lessons:
                handle.write(lesson.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
