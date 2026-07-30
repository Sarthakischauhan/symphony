"""Coding-agent tools: one module per tool, shared workspace base.

Pattern for adding a tool:
1. Create ``coding_agent/tools/<name>.py`` with a ``WorkspaceTool`` subclass
2. Set ``name`` / ``description`` and implement ``run(...)``
3. Register the class in ``TOOL_CLASSES`` below
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Type

from core_harness import Tool

from coding_agent.tools.base import WorkspaceTool
from coding_agent.tools.bash import BashTool
from coding_agent.tools.grep import GrepTool
from coding_agent.tools.read_file import ReadFileTool
from coding_agent.tools.write_file import WriteFileTool

TOOL_CLASSES: tuple[Type[WorkspaceTool], ...] = (
    ReadFileTool,
    WriteFileTool,
    BashTool,
    GrepTool,
)

__all__ = [
    "BashTool",
    "GrepTool",
    "ReadFileTool",
    "TOOL_CLASSES",
    "WorkspaceTool",
    "WriteFileTool",
    "build_tools",
]


def build_tools(workspace: str | Path) -> List[Tool]:
    """Instantiate every registered workspace tool for ``workspace``."""
    return [cls(workspace).as_harness_tool() for cls in TOOL_CLASSES]
