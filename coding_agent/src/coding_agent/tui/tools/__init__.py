"""Tool-call widgets and image attachments for the TUI."""

from coding_agent.tui.tools.calls import (
    BashToolHeader,
    BashToolWidget,
    GenerateImageWidget,
    PatchDiffWidget,
    ReadFileWidget,
    ToolCallSnapshot,
    ToolCallSummary,
    ToolCallWidget,
    make_tool_widget,
)
from coding_agent.tui.tools.diff import diff_stats, make_unified_diff
from coding_agent.tui.tools.images import (
    IMAGE_MARKER_RE,
    ImageAttachment,
    ImageModal,
    build_user_content,
    display_from_content,
    dropped_image_paths,
    render_half_block,
)

__all__ = [
    "BashToolHeader",
    "BashToolWidget",
    "GenerateImageWidget",
    "IMAGE_MARKER_RE",
    "ImageAttachment",
    "ImageModal",
    "PatchDiffWidget",
    "ReadFileWidget",
    "ToolCallSnapshot",
    "ToolCallSummary",
    "ToolCallWidget",
    "build_user_content",
    "diff_stats",
    "display_from_content",
    "dropped_image_paths",
    "make_tool_widget",
    "make_unified_diff",
    "render_half_block",
]
