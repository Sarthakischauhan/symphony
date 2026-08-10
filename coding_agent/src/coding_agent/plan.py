"""Workspace storage for the latest agent plan."""

from __future__ import annotations

from pathlib import Path


class PlanStore:
    def __init__(self, workspace: str | Path) -> None:
        self.path = Path(workspace).resolve() / ".symphony" / "plan.md"

    def save(self, task: str, plan: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = f"# Plan\n\n**Task:** {task.strip()}\n\n{plan.strip()}\n"
        self.path.write_text(content, encoding="utf-8")

    def load(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def to_markdown(self) -> str:
        return self.load() or "# Plan\n\n_No plan created yet for this workspace._\n"
