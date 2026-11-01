"""App chrome: the top bar and footer that frame the transcript and composer."""

from coding_agent.tui.chrome.footer import (
    ComposerOverlay,
    context_percent,
    footer_hint,
    footer_segments,
    phase_label,
    render_footer,
    StatusBar,
)
from coding_agent.tui.chrome.session import SessionChrome, artifact_key
from coding_agent.tui.chrome.topbar import (
    TopBar,
    display_workspace_path,
    read_git_branch,
    read_git_dirty,
    running_background_tasks,
    short_model_name,
    topbar_text,
)

__all__ = [
    "ComposerOverlay",
    "SessionChrome",
    "TopBar",
    "artifact_key",
    "context_percent",
    "display_workspace_path",
    "footer_hint",
    "footer_segments",
    "StatusBar",
    "phase_label",
    "read_git_branch",
    "read_git_dirty",
    "render_footer",
    "running_background_tasks",
    "short_model_name",
    "topbar_text",
]
