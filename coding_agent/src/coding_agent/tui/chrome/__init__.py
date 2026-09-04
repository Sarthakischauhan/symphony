"""App chrome: the top bar and footer that frame the transcript and composer."""

from coding_agent.tui.chrome.footer import (
    context_percent,
    footer_hint,
    footer_segments,
    phase_label,
    render_footer,
)
from coding_agent.tui.chrome.topbar import (
    TopBar,
    display_workspace_path,
    read_git_branch,
    topbar_text,
)

__all__ = [
    "TopBar",
    "context_percent",
    "display_workspace_path",
    "footer_hint",
    "footer_segments",
    "phase_label",
    "read_git_branch",
    "render_footer",
    "topbar_text",
]
