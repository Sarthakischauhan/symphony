"""Shared styling for modal controls."""

from __future__ import annotations


MODAL_BASE_CSS = """
#modal-close {
    dock: right;
    width: 3;
    height: 3;
    color: #a0a0a0;
    content-align: center middle;
    background: #101010;
    border: round #343434;
}

#modal-close:hover,
#modal-close:focus {
    color: #f2d675;
    background: #303030;
}

.modal-pane {
    width: 86%;
    max-width: 132;
    height: 84%;
    padding: 2 3;
    background: #101010;
    border: round #383838;
}

.modal-body {
    width: 100%;
    height: 1fr;
    padding: 1 1 2 1;
    scrollbar-size: 1 1;
    scrollbar-color: #343434;
    scrollbar-color-active: #525252;
    scrollbar-color-hover: #484848;
    scrollbar-background: #101010;
    scrollbar-background-active: #101010;
    scrollbar-background-hover: #101010;
}

.content-card {
    width: 100%;
    height: auto;
    margin-bottom: 2;
    padding: 1 2 2 2;
    color: #bdbdbd;
    background: #121212;
    border-top: solid #303030;
}

.empty-state {
    width: 100%;
    height: auto;
    padding: 4 5;
    margin: 2 0;
    content-align: center middle;
    text-align: center;
    background: #121212;
}

.modal-footer {
    width: 100%;
    height: 2;
    padding: 1 1 0 1;
    color: #686868;
    background: #101010;
}
"""


CONTENT_MODAL_CSS = MODAL_BASE_CSS + """
ContentModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#content-pane {
    border: round #38474a;
}

#content-text {
    width: 100%;
    height: auto;
    padding: 1 2;
    color: #d0d0d0;
    background: #0d0d0d;
}
"""
