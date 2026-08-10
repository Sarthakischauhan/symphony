"""Workspace storage for agent plans."""

from __future__ import annotations

import re
from pathlib import Path


class PlanStore:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self._latest_path = self.workspace / ".symphony" / "latest-plan"
        self._stream_task: str | None = None
        self._stream_text = ""

    @staticmethod
    def filename_for(task: str) -> str:
        """Return a readable, workspace-safe filename for a task."""
        slug = re.sub(r"[^a-z0-9]+", "_", task.strip().lower()).strip("_")
        slug = slug[:80].rstrip("_") or "implementation"
        return f"{slug}_plan.md"

    @property
    def path(self) -> Path:
        """Return the most recently selected plan path."""
        try:
            filename = self._latest_path.read_text(encoding="utf-8").strip()
        except OSError:
            filename = ""
        if filename and Path(filename).name == filename:
            return self.workspace / filename
        return self.workspace / ".symphony" / "plan.md"

    def begin(self, task: str) -> Path:
        """Create a task-named plan and make it the current plan."""
        path = self.workspace / self.filename_for(task)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._latest_path.parent.mkdir(parents=True, exist_ok=True)
        self._latest_path.write_text(path.name, encoding="utf-8")
        self._stream_task = task.strip()
        self._stream_text = ""
        path.write_text(
            f"# Plan\n\n**Task:** {self._stream_task}\n\n", encoding="utf-8"
        )
        return path

    def append(self, text: str) -> None:
        """Persist a streamed piece of the current plan immediately."""
        if not text:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._stream_task is None:
            with self.path.open("a", encoding="utf-8") as plan_file:
                plan_file.write(text)
            return
        self._stream_text += text
        self.path.write_text(
            f"# Plan\n\n**Task:** {self._stream_task}\n\n{self._stream_text}",
            encoding="utf-8",
        )

    def save(self, task: str, plan: str) -> None:
        self.begin(task)
        self.append(f"{plan.strip()}\n")

    def load(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def to_markdown(self) -> str:
        return self.load() or "# Plan\n\n_No plan created yet for this workspace._\n"
