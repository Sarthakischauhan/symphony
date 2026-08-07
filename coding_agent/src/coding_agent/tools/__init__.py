"""Workspace-scoped tools for the coding agent."""

from pathlib import Path
from typing import List, Type

from core_harness import Tool

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.tools.bash import BashArgs, BashTool
from coding_agent.tools.patch import PatchArgs, PatchTool
from coding_agent.tools.read_file import ReadFileArgs, ReadFileTool
from coding_agent.tools.search import SearchArgs, SearchTool
from coding_agent.tools.write_file import WriteFileArgs, WriteFileTool

TOOL_CLASSES: tuple[Type[WorkspaceTool], ...] = (
    ReadFileTool,
    WriteFileTool,
    PatchTool,
    BashTool,
    SearchTool,
)

__all__ = [
    "BashArgs", "BashTool", "PatchArgs", "PatchTool", "ReadFileArgs",
    "ReadFileTool", "SearchArgs", "SearchTool", "TOOL_CLASSES",
    "ToolArgsModel", "WorkspaceTool", "WriteFileArgs", "WriteFileTool", "build_tools",
]


def build_tools(workspace: str | Path) -> List[Tool]:
    return [tool_class(workspace).as_harness_tool() for tool_class in TOOL_CLASSES]
