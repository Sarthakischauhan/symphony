"""Coding-agent tools."""

from pathlib import Path
from typing import List, Type

from core_harness import Tool

from coding_agent.config import ToolsConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.tools.ask_user import AskUserArgs, AskUserTool
from coding_agent.tools.bash import BashArgs, BashTool
from coding_agent.tools.generate_image import GenerateImageArgs, GenerateImageTool
from coding_agent.tools.memory import MemoryArgs, MemoryTool
from coding_agent.tools.patch import PatchArgs, PatchTool
from coding_agent.tools.enter_plan_mode import EnterPlanModeTool
from coding_agent.tools.exit_plan_mode import ExitPlanModeTool
from coding_agent.tools.read_file import ReadFileArgs, ReadFileTool
from coding_agent.tools.search import SearchArgs, SearchTool
from coding_agent.tools.write_file import WriteFileArgs, WriteFileTool

TOOL_CLASSES: tuple[Type[WorkspaceTool], ...] = (
    ReadFileTool,
    WriteFileTool,
    GenerateImageTool,
    MemoryTool,
    PatchTool,
    BashTool,
    SearchTool,
    AskUserTool,
)

__all__ = [
    "AskUserArgs", "AskUserTool", "BashArgs", "BashTool",
    "GenerateImageArgs", "GenerateImageTool", "MemoryArgs", "MemoryTool", "PatchArgs", "PatchTool",
    "ReadFileArgs", "ReadFileTool", "SearchArgs", "SearchTool", "EnterPlanModeTool", "ExitPlanModeTool", "TOOL_CLASSES",
    "ToolArgsModel", "WorkspaceTool", "WriteFileArgs", "WriteFileTool", "build_tools",
]


def build_tools(
    workspace: str | Path,
    *,
    config: ToolsConfig | None = None,
    learning_enabled: bool = False,
) -> List[Tool]:
    tools_config = config or ToolsConfig()
    configured = {
        BashTool: {"config": tools_config.bash},
        ReadFileTool: {"config": tools_config.read_file},
        SearchTool: {"config": tools_config.search},
    }
    classes = TOOL_CLASSES if learning_enabled else tuple(
        tool for tool in TOOL_CLASSES if tool is not MemoryTool
    )
    return [
        tool_class(workspace, **configured.get(tool_class, {})).as_harness_tool()
        for tool_class in classes
    ]
