"""Small in-session setup form for Langfuse credentials."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input, Static

from coding_agent.credentials import global_env_path, upsert_dotenv
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton


class LangfuseSetupScreen(ModalBase[bool]):
    """Collect Langfuse credentials without displaying the secret key."""

    # Match the provider onboarding modal: a full-size, dark modal pane with
    # the same header, input, error, and footer treatment.
    CSS = """
    LangfuseSetupScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.52);
    }

    #langfuse-pane {
        width: 98%;
        max-width: 180;
        height: 94%;
        padding: 0 1;
        background: #0A0A0A;
        border: round #262626;
    }

    #langfuse-pane > #modal-close {
        background: #0A0A0A;
    }

    #langfuse-title {
        width: 100%;
        height: 3;
        min-height: 3;
        padding: 1 8 0 1;
        color: #d9dde0;
        text-style: bold;
        background: #0A0A0A;
        border-bottom: solid #262626;
    }

    #langfuse-subtitle {
        width: 100%;
        height: 2;
        padding: 1 1 0 1;
        color: #858d91;
        background: #0A0A0A;
    }

    #langfuse-pane Input {
        width: 100%;
        height: 3;
        margin: 1 1 0 1;
        background: #141414;
        color: #ededed;
        border: tall #2a2a2a;
    }

    #langfuse-pane Input:focus {
        border: tall #e1c16e;
    }

    #langfuse-error {
        height: 1;
        margin: 1 1 0 1;
        color: #db6767;
    }

    #langfuse-hint {
        width: 100%;
        height: 2;
        padding: 1 1 0 1;
        color: #686868;
        background: #0A0A0A;
        border-top: solid #262626;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="langfuse-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static("Langfuse setup", id="langfuse-title")
            yield Static(
                "Send run traces to Langfuse. Keys are saved to ~/.symphony/.env (0600).",
                id="langfuse-subtitle",
            )
            yield Input(
                value=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
                placeholder="pk-lf-...",
                id="langfuse-public-key",
            )
            yield Input(
                placeholder="sk-lf-...",
                password=True,
                id="langfuse-secret-key",
            )
            yield Input(
                value=os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
                placeholder="https://cloud.langfuse.com",
                id="langfuse-base-url",
            )
            yield Static("Enter submits · Esc cancels", id="langfuse-hint")
            yield Static("", id="langfuse-error")

    def on_mount(self) -> None:
        self.query_one("#langfuse-public-key", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "langfuse-public-key":
            self.query_one("#langfuse-secret-key", Input).focus()
            return
        if event.input.id == "langfuse-secret-key":
            self.query_one("#langfuse-base-url", Input).focus()
            return
        public_key = self.query_one("#langfuse-public-key", Input).value.strip()
        secret_key = self.query_one("#langfuse-secret-key", Input).value.strip()
        base_url = self.query_one("#langfuse-base-url", Input).value.strip()
        if not public_key or not secret_key:
            self.query_one("#langfuse-error", Static).update(
                "Public and secret keys are required."
            )
            return
        updates = {
            "LANGFUSE_PUBLIC_KEY": public_key,
            "LANGFUSE_SECRET_KEY": secret_key,
        }
        if base_url:
            updates["LANGFUSE_BASE_URL"] = base_url
        upsert_dotenv(global_env_path(), updates)
        os.environ.update(updates)
        self.dismiss(True)


__all__ = ["LangfuseSetupScreen"]
