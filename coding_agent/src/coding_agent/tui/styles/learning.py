"""CSS for the agent learnings modal."""

from __future__ import annotations

from coding_agent.tui.styles.modal import MODAL_BASE_CSS

LEARNING_MODAL_CSS = MODAL_BASE_CSS + """
LearningModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#learning-pane {
    border: round #38454b;
}

#learning-hint {
    text-align: right;
}

"""
