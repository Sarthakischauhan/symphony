"""App chrome: the top bar and footer that frame the transcript and composer."""

from coding_agent.tui.chrome.footer import (
    ComposerOverlay,
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
    provider_logo,
    provider_mark,
    read_git_dirty,
    short_model_name,
    topbar_text,
)

__all__ = [
    "ComposerOverlay",
    "TopBar",
    "context_percent",
    "display_workspace_path",
    "footer_hint",
    "footer_segments",
    "phase_label",
    "provider_logo",
    "provider_mark",
    "read_git_branch",
    "read_git_dirty",
    "render_footer",
    "short_model_name",
    "topbar_text",
]
