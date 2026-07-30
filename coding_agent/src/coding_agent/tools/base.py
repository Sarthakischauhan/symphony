"""Shared workspace binding and path safety for coding-agent tools.

Every tool module follows the same pattern:
1. Subclass ``WorkspaceTool``
2. Set ``name`` and ``description``
3. Implement ``run(...)`` with typed parameters
4. Export the class; ``build_tools`` wires them into ``core_harness.Tool``
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core_harness import Tool


class WorkspaceTool(ABC):
    """Base class for tools scoped to a workspace root."""

    name: str
    description: str

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, path: str) -> Path:
        """Resolve a workspace-relative path; reject escapes."""
        target = (self.workspace / path).resolve()
        if not target.is_relative_to(self.workspace):
            raise ValueError(f"Path escapes workspace: {path}")
        return target

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> str:
        """Execute the tool and return a string result for the model."""

    def as_harness_tool(self) -> Tool:
        """Wrap ``run`` as a ``core_harness.Tool`` with this tool's schema metadata."""
        return Tool(self.run, name=self.name, description=self.description)
