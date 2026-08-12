"""CSS for the current plan modal."""

from __future__ import annotations

from coding_agent.tui.styles.modal import MODAL_BASE_CSS

PLAN_MODAL_CSS = MODAL_BASE_CSS + """
PlanModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#plan-pane {
    border-left: solid #81754e;
}

#plan-body {
    padding-top: 1;
}

#plan-hint {
    width: 1fr;
    height: 2;
    padding: 1 0 0 1;
    color: #686868;
}

#plan-actions {
    width: 100%;
    height: 3;
    background: #1b1b1b;
}

#plan-build {
    width: 16;
    height: 3;
    padding: 1 1;
    color: #c7b66e;
    content-align: center middle;
    background: #27251e;
    border-left: solid #5a5132;
}

#plan-build:hover,
#plan-build:focus {
    color: #f2d675;
    background: #302c20;
}

"""
