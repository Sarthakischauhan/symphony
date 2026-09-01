"""Modal CSS tokens for the coding-agent TUI."""

from __future__ import annotations

MODAL_BASE_CSS = """
#modal-close {
    dock: right;
    width: 7;
    height: 1;
    color: #737373;
    content-align: right middle;
    background: #101010;
}

#modal-close:hover,
#modal-close:focus {
    color: #f2d675;
    text-style: bold;
    background: #101010;
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


IMAGE_MODAL_CSS = MODAL_BASE_CSS + """
ImageModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#content-pane {
    border: round #38474a;
}

#image-title {
    width: 100%;
    height: auto;
    padding: 0 1 1 1;
    color: #d0d0d0;
    background: #101010;
}

#image-preview {
    width: 100%;
    height: auto;
    padding: 1 1;
    background: #0d0d0d;
}
"""

# --- diff.py ---
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

# --- learning.py ---
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

# --- plan.py ---
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

# --- context.py ---
CONTEXT_MODAL_CSS = MODAL_BASE_CSS + """
ContextModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#context-pane {
    width: 82%;
    max-width: 118;
    height: 78%;
    max-height: 44;
    padding: 1 2;
    background: #101010;
    border: round #38474a;
}

#context-header {
    width: 100%;
    height: 2;
    background: #101010;
}

#context-title {
    width: 1fr;
    height: 1;
    color: #d8d8d8;
    text-style: bold;
    background: #101010;
}

#context-meters {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    padding: 1 2;
    background: #0d0d0d;
    border-top: solid #2a2a2a;
}

#context-buckets {
    width: 100%;
    height: 3;
    margin-bottom: 1;
    background: #101010;
    border-bottom: solid #252525;
}

.context-chip {
    width: auto;
    height: 3;
    margin-right: 2;
    padding: 0 1 1 1;
    color: #9a9a9a;
    content-align: center middle;
    background: #101010;
}

.context-chip:hover,
.context-chip:focus {
    color: #e6e6e6;
    background: #161616;
}

.context-chip-active {
    color: #f2d675;
    text-style: bold;
    background: #101010;
    border-bottom: heavy #8f835a;
}

#context-meta {
    width: 100%;
    height: 2;
    padding: 0 1 1 1;
    color: #686868;
    background: #101010;
}

#context-body {
    padding: 0;
    background: #101010;
}

#context-list {
    width: 100%;
    height: auto;
    padding: 1 2;
    background: #0d0d0d;
    border-top: solid #252525;
}

.context-row {
    width: 100%;
    height: auto;
}

#context-hint {
    text-align: right;
    padding-right: 0;
}
"""

