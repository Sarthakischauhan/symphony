"""CSS for the agent learnings modal."""

from __future__ import annotations

LEARNING_MODAL_CSS = """
LearningModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.7);
}

#learning-pane {
    width: 95%;
    height: 90%;
    padding: 1 2;
    background: #1b1b1b;
    border-left: solid #454545;
}

#learning-title {
    height: 1;
    color: #d0d0d0;
    padding-bottom: 1;
}

#learning-body {
    width: 100%;
    height: 1fr;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-color-hover: #606060;
    scrollbar-background: #1b1b1b;
}

#learning-markdown {
    width: 100%;
    height: auto;
    color: #d0d0d0;
}

#learning-hint {
    height: 1;
    color: #767676;
    text-align: right;
    padding-top: 1;
}
"""
