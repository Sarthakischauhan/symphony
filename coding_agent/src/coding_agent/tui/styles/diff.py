"""CSS for the workspace diff modal."""

from __future__ import annotations

from coding_agent.tui.styles.modal import MODAL_BASE_CSS

DIFF_MODAL_CSS = MODAL_BASE_CSS + """
DiffModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#diff-pane {
    border-left: solid #617d69;
}

#diff-hint {
    text-align: right;
}

.diff-file-card {
    padding: 1 1;
}
"""
