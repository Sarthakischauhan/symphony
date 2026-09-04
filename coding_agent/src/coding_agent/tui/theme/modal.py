"""Modal CSS tokens for the coding-agent TUI."""

from __future__ import annotations

MODAL_BASE_CSS = """
#modal-close {
    dock: right;
    width: 7;
    height: 1;
    color: #737373;
    content-align: right middle;
    background: #0A0A0A;
}

#modal-close:hover,
#modal-close:focus {
    color: #f2d675;
    text-style: bold;
    background: #0A0A0A;
}

.modal-pane {
    width: 86%;
    max-width: 132;
    height: 84%;
    padding: 2 3;
    background: #0A0A0A;
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
    scrollbar-background: #0A0A0A;
    scrollbar-background-active: #0A0A0A;
    scrollbar-background-hover: #0A0A0A;
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
    background: #0A0A0A;
}
"""


CONTENT_MODAL_CSS = MODAL_BASE_CSS + """
ContentModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#content-pane {
    width: 98%;
    max-width: 180;
    height: 94%;
    padding: 0 1;
    border: round #262626;
}

#content-body {
    padding: 0;
    background: #0A0A0A;
}

#content-pane .modal-footer {
    padding-left: 1;
}

#content-title {
    width: 100%;
    height: auto;
    padding: 0 1 1 1;
    color: #d0d0d0;
    text-style: bold;
    background: #0A0A0A;
}

#content-text {
    display: none;
}

#content-numbered {
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
    width: 98%;
    max-width: 180;
    height: 94%;
    padding: 0 1;
    border: round #262626;
}

#content-body {
    padding: 0;
    background: #0A0A0A;
}

#content-pane .modal-footer {
    padding-left: 1;
}

#image-title {
    width: 100%;
    height: auto;
    padding: 0 1 1 1;
    color: #d0d0d0;
    background: #0A0A0A;
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
    width: 98%;
    max-width: 180;
    height: 94%;
    padding: 0 1;
    background: #0A0A0A;
    border: round #262626;
}

#diff-header {
    width: 100%;
    height: 3;
    min-height: 3;
    padding: 1 1 0 1;
    border-bottom: solid #262626;
    background: #0A0A0A;
}

#diff-pane > #modal-close {
    display: none;
}


#diff-title {
    width: auto;
    color: #d9dde0;
    text-style: bold;
    background: #0A0A0A;
}

#diff-path {
    width: auto;
    padding-left: 2;
    color: #aeb8bc;
    background: #0A0A0A;
}

#diff-header-spacer {
    width: 1fr;
    background: #0A0A0A;
}

#diff-total-stats {
    width: auto;
    margin-left: 2;
    background: #0A0A0A;
}

#diff-file-counter {
    width: auto;
    margin-left: 2;
    color: #858d91;
    content-align: right middle;
    background: #0A0A0A;
}

#diff-header #modal-close {
    dock: none;
    width: auto;
    min-width: 11;
    margin-left: 2;
    color: #858d91;
    background: #0A0A0A;
}

#diff-pane #modal-close:hover,
#diff-pane #modal-close:focus {
    color: #f2d675;
    background: #171b1c;
}

#diff-body {
    height: 1fr;
    padding: 0;
    background: #0A0A0A;
    scrollbar-color: #343434;
    scrollbar-color-active: #525252;
    scrollbar-color-hover: #484848;
    scrollbar-background: #0A0A0A;
    scrollbar-background-active: #0A0A0A;
    scrollbar-background-hover: #0A0A0A;
}

#diff-hint {
    width: 100%;
    height: 2;
    content-align: center middle;
    color: #737b7f;
    background: #0A0A0A;
}

.diff-file-card {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    padding: 0;
    background: #0A0A0A;
    border-top: solid #262626;
}

.diff-file-card.inactive {
    display: none;
}

.diff-file-card.collapsed .diff-patch {
    display: none;
}

.diff-file-card:hover {
    border-top: solid #687b83;
}

.diff-file-header {
    width: 100%;
    height: 1;
    padding: 0 1;
    background: #171717;
}

.diff-file-chevron {
    width: 3;
    color: #8ca0a8;
    content-align: center middle;
    background: #171717;
}

.diff-file-path {
    width: 1fr;
    height: 1;
    content-align: left middle;
    color: #d0d0d0;
    background: #171717;
}

.diff-file-card.selected {
    border-top: solid #f2d675;
}

.diff-file-card.selected .diff-file-chevron {
    color: #f2d675;
}

.diff-file-card.selected .diff-file-path {
    color: #f2d675;
}

.diff-file-stats {
    width: auto;
    height: 1;
    content-align: right middle;
    color: #737373;
    background: #171717;
}

.diff-patch {
    width: 100%;
    height: auto;
    margin: 0;
    padding: 0 1 1 1;
    color: #b8bec1;
    background: #080a0b;
}
"""

# --- learning.py ---
LEARNING_MODAL_CSS = MODAL_BASE_CSS + """
LearningModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#learning-pane {
    width: 98%;
    max-width: 180;
    height: 94%;
    padding: 0 1;
    background: #0A0A0A;
    border: round #262626;
}

#learning-pane > #modal-close {
    display: none;
}

#learning-header {
    width: 100%;
    height: 3;
    min-height: 3;
    padding: 1 1 0 1;
    border-bottom: solid #262626;
    background: #0A0A0A;
}

#learning-title {
    width: auto;
    color: #d9dde0;
    text-style: bold;
    background: #0A0A0A;
}

#learning-counter {
    width: 1fr;
    padding-left: 2;
    color: #858d91;
    background: #0A0A0A;
}

#learning-header #modal-close {
    dock: none;
    width: auto;
    min-width: 11;
    color: #858d91;
    background: #0A0A0A;
}

#learning-header #modal-close:hover,
#learning-header #modal-close:focus {
    color: #f2d675;
    background: #171b1c;
}

#learning-body {
    height: 1fr;
    padding: 0;
    background: #0A0A0A;
}

#learning-hint {
    width: 100%;
    height: 2;
    content-align: center middle;
    color: #737b7f;
    background: #0A0A0A;
}

.learning-card {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    padding: 0;
    background: #0A0A0A;
    border-top: solid #262626;
}

.learning-card:hover {
    border-top: solid #687b83;
}

.learning-card-header {
    width: 100%;
    height: 1;
    padding: 0 1;
    background: #171717;
}

.learning-marker {
    width: 3;
    color: #c5a9e6;
    content-align: center middle;
    background: #171717;
}

.learning-card-title {
    width: 1fr;
    color: #d0d0d0;
    background: #171717;
}

.learning-meta {
    width: auto;
    background: #171717;
}

.learning-body-content {
    width: 100%;
    height: auto;
    padding: 1 2 2 2;
    color: #bdbdbd;
    background: #0A0A0A;
}

"""

# --- plan.py ---
PLAN_MODAL_CSS = MODAL_BASE_CSS + """
PlanModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.52);
}

#plan-pane {
    width: 98%;
    max-width: 180;
    height: 94%;
    padding: 0 1;
    background: #0A0A0A;
    border: round #262626;
}

#plan-pane > #modal-close {
    display: none;
}

#plan-body {
    height: 1fr;
    padding: 0;
    background: #0A0A0A;
}

.plan-section-card {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    padding: 0;
    background: #0A0A0A;
    border-top: solid #262626;
}

.plan-section-card:hover {
    border-top: solid #687b83;
}

.plan-section-header {
    width: 100%;
    height: 1;
    padding: 0 1;
    background: #171717;
}

.plan-section-number {
    width: 4;
    color: #c7b66e;
    text-style: bold;
    content-align: left middle;
    background: #171717;
}

.plan-section-title {
    width: 1fr;
    color: #d0d0d0;
    text-style: bold;
    background: #171717;
}

.plan-section-body {
    width: 100%;
    height: auto;
    padding: 1 1 2 1;
    color: #bdbdbd;
    background: #0A0A0A;
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
    background: #0A0A0A;
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
    background: #0A0A0A;
    border: round #38474a;
}

#context-header {
    width: 100%;
    height: 2;
    background: #0A0A0A;
}

#context-title {
    width: 1fr;
    height: 1;
    color: #d8d8d8;
    text-style: bold;
    background: #0A0A0A;
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
    background: #0A0A0A;
    border-bottom: solid #252525;
}

.context-chip {
    width: auto;
    height: 3;
    margin-right: 2;
    padding: 0 1 1 1;
    color: #9a9a9a;
    content-align: center middle;
    background: #0A0A0A;
}

.context-chip:hover,
.context-chip:focus {
    color: #e6e6e6;
    background: #161616;
}

.context-chip-active {
    color: #f2d675;
    text-style: bold;
    background: #0A0A0A;
    border-bottom: heavy #8f835a;
}

#context-meta {
    width: 100%;
    height: 2;
    padding: 0 1 1 1;
    color: #686868;
    background: #0A0A0A;
}

#context-body {
    padding: 0;
    background: #0A0A0A;
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

