"""Shared styling for modal controls."""

from __future__ import annotations


MODAL_BASE_CSS = """
#modal-close {
    dock: right;
    width: 3;
    height: 1;
    color: #a0a0a0;
    content-align: center middle;
    background: #1b1b1b;
}

#modal-close:hover,
#modal-close:focus {
    color: #f2d675;
    background: #303030;
}
"""
