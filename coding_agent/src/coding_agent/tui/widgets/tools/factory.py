"""Tool widget factory."""

from coding_agent.tui.widgets.tools.base import ToolCallWidget
from coding_agent.tui.widgets.tools.bash import BashToolWidget
from coding_agent.tui.widgets.tools.generate_image import GenerateImageWidget
from coding_agent.tui.widgets.tools.patch import PatchDiffWidget
from coding_agent.tui.widgets.tools.read_file import ReadFileWidget


def make_tool_widget(call_id: str, tool_name: str) -> ToolCallWidget:
    if tool_name == "bash":
        return BashToolWidget(call_id, tool_name)
    if tool_name == "read_file":
        return ReadFileWidget(call_id, tool_name)
    if tool_name == "generate_image":
        return GenerateImageWidget(call_id, tool_name)
    if tool_name == "patch":
        return PatchDiffWidget(call_id, tool_name)
    return ToolCallWidget(call_id, tool_name)
