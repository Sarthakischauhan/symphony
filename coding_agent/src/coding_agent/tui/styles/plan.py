"""CSS for the current plan modal."""

from __future__ import annotations

from coding_agent.tui.styles.modal import MODAL_BASE_CSS

PLAN_MODAL_CSS = MODAL_BASE_CSS + """
PlanModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#plan-pane {
    border: round #4a4532;
}

#plan-body {
    padding-top: 0;
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
    background: #101010;
}

#plan-build {
    width: 16;
    height: 3;
    padding: 0 1;
    color: #c7b66e;
    content-align: center middle;
    background: #181712;
    border: round #4a4532;
}

#plan-build:hover,
#plan-build:focus {
    color: #f2d675;
    background: #302c20;
}

"""
