"""Coding-agent tools: one module per tool, shared workspace base.

Pattern for adding a tool:
1. Create ``coding_agent/tools/<name>.py`` with a ``WorkspaceTool`` subclass
2. Define a pydantic ``ToolArgsModel`` with Field descriptions
3. Set ``name`` / ``description`` / ``args_model`` and implement ``run(...)``
4. Register the class in ``TOOL_CLASSES`` below
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Type

from core_harness import Tool

from coding_agent.tools.ast_query import AstQueryArgs, AstQueryTool
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.tools.bash import BashArgs, BashTool
from coding_agent.tools.grep import GrepArgs, GrepTool
from coding_agent.tools.patch import PatchArgs, PatchTool
from coding_agent.tools.read_file import ReadFileArgs, ReadFileTool
from coding_agent.tools.write_file import WriteFileArgs, WriteFileTool

TOOL_CLASSES: tuple[Type[WorkspaceTool], ...] = (
    ReadFileTool,
    WriteFileTool,
    PatchTool,
    BashTool,
    GrepTool,
    AstQueryTool,
)

__all__ = [
    "AstQueryArgs",
    "AstQueryTool",
    "BashArgs",
    "BashTool",
    "GrepArgs",
    "GrepTool",
    "PatchArgs",
    "PatchTool",
    "ReadFileArgs",
    "ReadFileTool",
    "TOOL_CLASSES",
    "ToolArgsModel",
    "WorkspaceTool",
    "WriteFileArgs",
    "WriteFileTool",
    "build_tools",
]


def build_tools(workspace: str | Path) -> List[Tool]:
    """Instantiate every registered workspace tool for ``workspace``."""
    return [cls(workspace).as_harness_tool() for cls in TOOL_CLASSES]
