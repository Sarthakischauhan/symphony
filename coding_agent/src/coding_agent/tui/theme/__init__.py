"""Color tokens and Textual CSS for the coding-agent TUI."""

from __future__ import annotations

from coding_agent.tui.theme.chrome import CHROME_CSS
from coding_agent.tui.theme.colors import (
    SYMPHONY_CODE_THEME,
    SYMPHONY_COLORS,
    SYMPHONY_RICH_THEME,
    SymphonyCodeStyle,
    themed_markdown,
)
from coding_agent.tui.theme.composer import COMPOSER_CSS
from coding_agent.tui.theme.modal import (
    CONTENT_MODAL_CSS,
    CONTEXT_MODAL_CSS,
    DIFF_MODAL_CSS,
    IMAGE_MODAL_CSS,
    LEARNING_MODAL_CSS,
    MODAL_BASE_CSS,
    PLAN_MODAL_CSS,
)
from coding_agent.tui.theme.resume import RESUME_CSS
from coding_agent.tui.theme.tools import TOOLS_CSS

APP_CSS = CHROME_CSS + TOOLS_CSS + COMPOSER_CSS

__all__ = [
    "APP_CSS",
    "CHROME_CSS",
    "COMPOSER_CSS",
    "CONTENT_MODAL_CSS",
    "CONTEXT_MODAL_CSS",
    "DIFF_MODAL_CSS",
    "IMAGE_MODAL_CSS",
    "LEARNING_MODAL_CSS",
    "MODAL_BASE_CSS",
    "PLAN_MODAL_CSS",
    "RESUME_CSS",
    "SYMPHONY_CODE_THEME",
    "SYMPHONY_COLORS",
    "SYMPHONY_RICH_THEME",
    "SymphonyCodeStyle",
    "TOOLS_CSS",
    "themed_markdown",
]
