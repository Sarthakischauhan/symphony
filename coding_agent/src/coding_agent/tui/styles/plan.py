"""CSS for the current plan modal."""

from __future__ import annotations

PLAN_MODAL_CSS = """
PlanModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.7);
}

#plan-pane {
    width: 95%;
    height: 90%;
    padding: 1 2;
    background: #1b1b1b;
    border-left: solid #454545;
}

#plan-title {
    height: 1;
    color: #d0d0d0;
    padding-bottom: 1;
}

#plan-body {
    width: 100%;
    height: 1fr;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-color-hover: #606060;
    scrollbar-background: #1b1b1b;
}

#plan-markdown {
    width: 100%;
    height: auto;
    color: #d0d0d0;
}

#plan-hint {
    width: 1fr;
    height: 1;
    color: #767676;
}

#plan-actions {
    width: 100%;
    height: 1;
    margin-top: 1;
    padding: 0 1;
    background: #202020;
}

#plan-build {
    width: 12;
    height: 1;
    color: #8a8a8a;
    text-align: right;
    background: #202020;
}

#plan-build:hover,
#plan-build:focus {
    color: #f2d675;
    text-style: underline;
}
"""
