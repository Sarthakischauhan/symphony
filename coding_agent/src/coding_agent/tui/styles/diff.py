"""CSS for the workspace diff modal."""

from __future__ import annotations

from coding_agent.tui.styles.modal import MODAL_BASE_CSS

DIFF_MODAL_CSS = MODAL_BASE_CSS + """
DiffModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#diff-pane {
    width: 92%;
    max-width: 150;
    height: 88%;
    padding: 1 2;
    background: #101010;
    border: round #3d3d3d;
}

#diff-pane #modal-close {
    background: #101010;
}

#diff-body {
    padding: 0 1;
    background: #101010;
    scrollbar-color: #343434;
    scrollbar-color-active: #525252;
    scrollbar-color-hover: #484848;
    scrollbar-background: #101010;
    scrollbar-background-active: #101010;
    scrollbar-background-hover: #101010;
}

#diff-hint {
    text-align: right;
    background: #101010;
}

.diff-file-card {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    padding: 1 0 0 0;
    background: #0d0d0d;
    border-top: solid #333333;
}

.diff-file-header {
    width: 100%;
    height: 1;
    padding: 0 1;
    background: #0d0d0d;
}

.diff-file-path {
    width: 1fr;
    height: 1;
    color: #d0d0d0;
    background: #0d0d0d;
}

.diff-file-stats {
    width: auto;
    height: 1;
    color: #737373;
    background: #0d0d0d;
}

.diff-patch {
    width: 100%;
    height: auto;
    margin-top: 1;
    padding: 0 1 1 1;
    background: #0a0a0a;
}
"""
