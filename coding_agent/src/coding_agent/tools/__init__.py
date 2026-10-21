"""Coding-agent tools."""

from pathlib import Path
from typing import List, Type

from core_harness import Tool

from coding_agent.config import ToolsConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.tools.ask_user import AskUserArgs, AskUserTool
from coding_agent.tools.bash import BashArgs, BashTool
from coding_agent.tools.bash_jobs import BashJobs
from coding_agent.tools.generate_image import GenerateImageArgs, GenerateImageTool
from coding_agent.tools.memory import MemoryArgs, MemoryGetTool, MemorySearchTool, MemoryTool
from coding_agent.tools.patch import PatchArgs, PatchTool
from coding_agent.tools.read_file import ReadFileArgs, ReadFileTool
from coding_agent.tools.save_artifact import SaveArtifactArgs, SaveArtifactTool
from coding_agent.tools.search import SearchArgs, SearchTool
from coding_agent.tools.web_search import WebSearchArgs, WebSearchTool
from coding_agent.tools.write_file import WriteFileArgs, WriteFileTool

TOOL_CLASSES: tuple[Type[WorkspaceTool], ...] = (
    ReadFileTool,
    WriteFileTool,
    GenerateImageTool,
    SaveArtifactTool,
    MemoryTool,
    MemorySearchTool,
    MemoryGetTool,
    PatchTool,
    BashTool,
    SearchTool,
    WebSearchTool,
    AskUserTool,
)

__all__ = [
    "AskUserArgs", "AskUserTool", "BashArgs", "BashJobs", "BashTool",
    "GenerateImageArgs", "GenerateImageTool", "MemoryArgs", "MemoryTool", "PatchArgs", "PatchTool",
    "ReadFileArgs", "ReadFileTool", "SaveArtifactArgs", "SaveArtifactTool", "SearchArgs", "SearchTool", "TOOL_CLASSES",
    "ToolArgsModel", "WebSearchArgs", "WebSearchTool", "WorkspaceTool", "WriteFileArgs", "WriteFileTool",
    "build_tools",
]


def build_tools(
    workspace: str | Path,
    *,
    config: ToolsConfig | None = None,
    learning_enabled: bool = False,
    unattended: bool = False,
    bash_jobs: BashJobs | None = None,
    learning_store: object | None = None,
) -> List[Tool]:
    tools_config = config or ToolsConfig()
    configured = {
        AskUserTool: {"unattended": unattended},
        BashTool: {"config": tools_config.bash, "jobs": bash_jobs},
        ReadFileTool: {"config": tools_config.read_file},
        SearchTool: {"config": tools_config.search},
        WebSearchTool: {"config": tools_config.web_search},
        MemoryTool: {"store": learning_store},
        MemorySearchTool: {"store": learning_store},
        MemoryGetTool: {"store": learning_store},
    }
    skipped: set[Type[WorkspaceTool]] = set()
    if not learning_enabled:
        skipped |= {MemoryTool, MemorySearchTool, MemoryGetTool}
    if not tools_config.web_search.enabled:
        skipped.add(WebSearchTool)
    classes = tuple(tool for tool in TOOL_CLASSES if tool not in skipped)
    return [
        tool_class(workspace, **configured.get(tool_class, {})).as_harness_tool()
        for tool_class in classes
    ]
