"""Workspace storage for agent plans."""

from __future__ import annotations

import re
from pathlib import Path


class PlanStore:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.plans_dir = self.workspace / ".symphony" / "plans"
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
            selected_path = self.plans_dir / filename
            if selected_path.exists():
                return selected_path
        legacy_path = self.workspace / ".symphony" / "plan.md"
        if legacy_path.exists():
            return legacy_path
        plans = self.list_paths()
        if plans:
            return plans[0]
        return self.plans_dir / "plan.md"

    def list_paths(self) -> tuple[Path, ...]:
        """Return stored plans with the current plan first, then newest mtime."""
        try:
            paths = list(self.plans_dir.glob("*.md"))
        except OSError:
            return ()
        latest_name = ""
        try:
            latest_name = self._latest_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return tuple(
            sorted(
                paths,
                key=lambda path: (
                    0 if path.name == latest_name else 1,
                    -path.stat().st_mtime_ns,
                    path.name,
                ),
            )
        )

    def select(self, value: str) -> Path | None:
        """Select a stored plan by filename or stem."""
        needle = value.strip().lower()
        matches = [
            path
            for path in self.list_paths()
            if needle in {path.name.lower(), path.stem.lower()}
        ]
        if len(matches) != 1:
            return None
        self._latest_path.parent.mkdir(parents=True, exist_ok=True)
        self._latest_path.write_text(matches[0].name, encoding="utf-8")
        return matches[0]

    @staticmethod
    def task_for(path: Path) -> str:
        """Read the task label from a plan, falling back to its filename."""
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:8]:
                if line.startswith("**Task:**"):
                    return line.removeprefix("**Task:**").strip()
        except OSError:
            pass
        return path.stem.removesuffix("_plan").replace("_", " ").title()

    def begin(self, task: str) -> Path:
        """Create or resume a task-named plan without resetting its stream."""
        path = self.plans_dir / self.filename_for(task)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self._latest_path.parent.mkdir(parents=True, exist_ok=True)
        self._latest_path.write_text(path.name, encoding="utf-8")
        task_text = task.strip()
        if self._stream_task == task_text and path.exists():
            return path
        self._stream_task = task_text
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        self._stream_text = existing.split("\n\n", 2)[-1] if existing.startswith("# Plan\n\n**Task:**") else ""
        if not existing:
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
        """Finalize a streamed plan without resetting its file or selection."""
        if self._stream_task is None or self.path.name != self.filename_for(task):
            self.begin(task)
        self._stream_task = task.strip()
        self._stream_text = plan.strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            f"# Plan\n\n**Task:** {self._stream_task}\n\n{self._stream_text}\n",
            encoding="utf-8",
        )

    def load(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def to_markdown(self) -> str:
        return self.load() or "# Plan\n\n_No plan created yet for this workspace._\n"
