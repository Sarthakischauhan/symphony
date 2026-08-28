"""Workspace-scoped tools for the coding agent."""

from pathlib import Path
from typing import List, Type

from core_harness import Tool

from coding_agent.config import DEFAULT_CODING_AGENT_CONFIG, ToolsConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.tools.ask_user import AskUserArgs, AskUserTool
from coding_agent.tools.bash import BashArgs, BashTool
from coding_agent.tools.generate_image import GenerateImageArgs, GenerateImageTool
from coding_agent.tools.patch import PatchArgs, PatchTool
from coding_agent.tools.read_file import ReadFileArgs, ReadFileTool
from coding_agent.tools.search import SearchArgs, SearchTool
from coding_agent.tools.write_file import WriteFileArgs, WriteFileTool

TOOL_CLASSES: tuple[Type[WorkspaceTool], ...] = (
    ReadFileTool,
    WriteFileTool,
    GenerateImageTool,
    PatchTool,
    BashTool,
    SearchTool,
    AskUserTool,
)

__all__ = [
    "AskUserArgs", "AskUserTool", "BashArgs", "BashTool",
    "GenerateImageArgs", "GenerateImageTool", "PatchArgs", "PatchTool",
    "ReadFileArgs", "ReadFileTool", "SearchArgs", "SearchTool", "TOOL_CLASSES",
    "ToolArgsModel", "WorkspaceTool", "WriteFileArgs", "WriteFileTool", "build_tools",
]


def build_tools(
    workspace: str | Path,
    *,
    config: ToolsConfig = DEFAULT_CODING_AGENT_CONFIG.tools,
) -> List[Tool]:
    configured = {
        BashTool: {"config": config.bash},
        ReadFileTool: {"config": config.read_file},
        SearchTool: {"config": config.search},
    }
    return [
        tool_class(workspace, **configured.get(tool_class, {})).as_harness_tool()
        for tool_class in TOOL_CLASSES
    ]
