"""CSS for the workspace diff modal."""

from __future__ import annotations

DIFF_MODAL_CSS = """
DiffModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.7);
}

#diff-pane {
    width: 95%;
    height: 90%;
    padding: 1 2;
    background: #1b1b1b;
    border-left: solid #454545;
}

#diff-title {
    height: 1;
    color: #d0d0d0;
    padding-bottom: 1;
}

#diff-body {
    width: 100%;
    height: 1fr;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-color-hover: #606060;
    scrollbar-background: #1b1b1b;
}

#diff-hint {
    height: 1;
    color: #767676;
    text-align: right;
    padding-top: 1;
}
"""
