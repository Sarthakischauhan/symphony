"""Session artifact list opened from the top bar."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.transcript.artifact import ArtifactRow


class ArtifactsScreen(ModalBase[None]):
    """List the latest versions of the session's artifacts."""

    CSS = """
    ArtifactsScreen { align: center middle; background: rgba(0, 0, 0, 0.52); }
    #artifacts-pane {
        width: 80; max-width: 90%; height: auto; max-height: 80%;
        padding: 0 1 1 1; background: #0A0A0A; border: round #262626;
    }
    #artifacts-title { height: 3; padding: 1 1 0 1; text-style: bold; color: #d9dde0; }
    #artifacts-list { height: auto; max-height: 20; }
    #artifacts-list .artifact { height: auto; padding: 0 1 1 1; }
    """

    def __init__(self, artifacts: list[tuple[str, str, Path]]) -> None:
        super().__init__()
        self.artifacts = artifacts

    def compose(self) -> ComposeResult:
        with Container(id="artifacts-pane"):
            yield ModalCloseButton("esc", id="modal-close")
            yield Static("Artifacts", id="artifacts-title")
            with ModalScroll(id="artifacts-list"):
                for title, detail, path in self.artifacts:
                    yield ArtifactRow(title, detail, path)
