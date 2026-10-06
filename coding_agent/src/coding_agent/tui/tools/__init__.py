"""Tool-call widgets and image attachments for the TUI."""

from coding_agent.tui.tools.calls import (
    BashToolHeader,
    GenerateImageWidget,
    PatchDiffWidget,
    ReadFileWidget,
    ToolCallWidget,
    diff_stats,
    make_tool_widget,
    make_unified_diff,
)
from coding_agent.tui.tools.images import (
    IMAGE_MARKER_RE,
    ImageAttachment,
    ImageModal,
    build_user_content,
    display_from_content,
    dropped_image_paths,
    textual_image,
)
from coding_agent.tui.tools.snapshots import (
    CompletedRunSummary,
    ToolCallSnapshot,
    ToolCallSummary,
    snapshot_from_call,
)

__all__ = [
    "BashToolHeader",
    "CompletedRunSummary",
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
    "snapshot_from_call",
    "textual_image",
]
