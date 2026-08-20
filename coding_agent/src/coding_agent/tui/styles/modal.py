"""Shared styling for modal controls."""

from __future__ import annotations


MODAL_BASE_CSS = """
#modal-close {
    dock: right;
    width: 3;
    height: 1;
    color: #858585;
    content-align: center middle;
    background: #171717;
}

#modal-close:hover,
#modal-close:focus {
    color: #f2d675;
    background: #303030;
}

.modal-pane {
    width: 82%;
    max-width: 124;
    height: 78%;
    padding: 1 2;
    background: #171717;
    border-left: solid #60717a;
}

.modal-header {
    width: 1fr;
    height: 4;
    padding: 0 1 1 1;
    color: #a8a8a8;
}

.modal-body {
    width: 100%;
    height: 1fr;
    padding: 0 1 1 0;
    scrollbar-size: 1 1;
    scrollbar-color: #484848;
    scrollbar-color-hover: #606060;
    scrollbar-background: #1b1b1b;
}

.content-card {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    padding: 1 1;
    color: #bdbdbd;
    background: #1d1d1d;
}

.empty-state {
    width: 100%;
    height: auto;
    padding: 3 4;
    margin-top: 1;
    content-align: center middle;
    text-align: center;
    background: #1d1d1d;
}

.modal-footer {
    width: 100%;
    height: 2;
    padding: 1 1 0 1;
    color: #686868;
}
"""


CONTENT_MODAL_CSS = MODAL_BASE_CSS + """
ContentModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#content-pane {
    border-left: solid #4f7374;
}

#content-text {
    width: 100%;
    height: auto;
    color: #d0d0d0;
}
"""
