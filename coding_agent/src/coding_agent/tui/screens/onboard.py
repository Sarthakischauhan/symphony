"""First-run and in-session wizard for adding model provider API keys."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from coding_agent.credentials import save_provider_key
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton
from coding_agent.tui.theme import ONBOARD_CSS, PROVIDER_MODAL_CSS, SYMPHONY_RICH_THEME
from core_ai.providers.catalog import (
    PROVIDERS,
    ProviderSpec,
    configured_provider_ids,
    get_provider,
)


def _provider_row(spec: ProviderSpec, configured: bool) -> Option:
    content = Text("› ")
    content.append(spec.label)
    content.append("\n  ")
    if configured:
        content.append("ready", style="#799e7c")
        content.append(f"   {spec.env_key}", style="#555555")
    else:
        content.append(spec.description, style="#737373")
    return Option(content, id=f"provider:{spec.id}")


def _continue_row(configured: tuple[str, ...]) -> Option:
    labels = ", ".join(get_provider(provider_id).label for provider_id in configured)
    content = Text("Continue")
    content.append("\n  ")
    content.append(f"Use {labels}", style="#737373")
    return Option(content, id="continue")


class ProviderWizard(Vertical):
    """Pick a provider, paste a key, optionally add another."""

    class Completed(Message):
        def __init__(self, providers: tuple[str, ...]) -> None:
            super().__init__()
            self.providers = providers

    def __init__(
        self,
        workspace: str | Path,
        *,
        initial_provider: str | None = None,
        first_run: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.workspace = Path(workspace)
        self.initial_provider = initial_provider
        self.first_run = first_run
        self.step: Literal["pick", "key"] = "pick"
        self._pending: str | None = None
        self._highlight_continue = False

    def compose(self) -> ComposeResult:
        yield Static("Add a provider", id="onboard-title")
        yield Static(
            "Choose where Symphony should send model calls. You can add more than one.",
            id="onboard-subtitle",
        )
        yield OptionList(id="provider-list")
        yield Input(password=True, id="provider-key")
        yield Static("", id="onboard-error")
        yield Static(self._hint_text(), id="onboard-hint")

    def on_mount(self) -> None:
        self.query_one("#provider-key", Input).display = False
        if self.initial_provider:
            self.show_key(self.initial_provider)
        else:
            self.show_pick()

    def show_pick(self) -> None:
        self.step = "pick"
        self._pending = None
        self.query_one("#onboard-title", Static).update("Add a provider")
        self.query_one("#onboard-subtitle", Static).update(
            "Choose where Symphony should send model calls. You can add more than one."
        )
        self.query_one("#onboard-error", Static).update("")
        self.query_one("#provider-key", Input).display = False
        listing = self.query_one("#provider-list", OptionList)
        listing.display = True
        self._refresh_list()
        listing.focus()
        self._set_hint()

    def show_key(self, provider_id: str) -> None:
        spec = get_provider(provider_id)
        self.step = "key"
        self._pending = provider_id
        self.query_one("#onboard-title", Static).update(f"{spec.label} API key")
        self.query_one("#onboard-subtitle", Static).update(
            f"Paste a key from {spec.docs_url}"
        )
        self.query_one("#onboard-error", Static).update("")
        self.query_one("#provider-list", OptionList).display = False
        key_input = self.query_one("#provider-key", Input)
        key_input.placeholder = spec.key_placeholder
        key_input.value = ""
        key_input.display = True
        key_input.focus()
        self._set_hint()

    def finish(self) -> None:
        self.post_message(self.Completed(configured_provider_ids()))

    def cancel(self) -> bool:
        """Handle Escape. Returns True when the host should close."""
        if self.step == "key":
            self.show_pick()
            return False
        self.finish()
        return True

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option_id = event.option_id or ""
        if option_id == "continue":
            self.finish()
            return
        if option_id.startswith("provider:"):
            self.show_key(option_id.split(":", 1)[1])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self._pending is None:
            return
        try:
            save_provider_key(self._pending, event.value)
        except ValueError as exc:
            self.query_one("#onboard-error", Static).update(str(exc))
            return
        self._highlight_continue = True
        self.show_pick()

    def _refresh_list(self) -> None:
        configured = configured_provider_ids()
        options = [_provider_row(spec, spec.id in configured) for spec in PROVIDERS]
        if configured:
            options.append(_continue_row(configured))
        listing = self.query_one("#provider-list", OptionList)
        listing.set_options(options)
        if configured and self._highlight_continue:
            listing.highlighted = listing.option_count - 1
            self._highlight_continue = False
        elif listing.option_count:
            listing.highlighted = 0

    def _hint_text(self) -> str:
        if self.step == "key":
            return "Enter save   Esc back"
        close = "skip" if self.first_run else "close"
        if configured_provider_ids():
            return f"↑↓ select   Enter add key   Continue starts   Esc {close}"
        return f"↑↓ select   Enter add key   Esc {close}"

    def _set_hint(self) -> None:
        self.query_one("#onboard-hint", Static).update(self._hint_text())


class OnboardApp(App[tuple[str, ...]]):
    """Full-screen first-run provider setup, matching the resume selector."""

    CSS = ONBOARD_CSS
    BINDINGS = [
        Binding("escape", "cancel", "skip"),
        Binding("ctrl+c", "cancel", "quit", show=False),
    ]

    def __init__(self, workspace: str | Path) -> None:
        super().__init__()
        self.workspace = Path(workspace)

    def compose(self) -> ComposeResult:
        with Container(id="onboard-page"):
            yield ProviderWizard(self.workspace, first_run=True)

    def on_mount(self) -> None:
        self.console.push_theme(SYMPHONY_RICH_THEME, inherit=True)
        wizard = self.query_one(ProviderWizard)
        if wizard.step == "pick":
            self.query_one("#provider-list", OptionList).focus()

    def on_provider_wizard_completed(self, event: ProviderWizard.Completed) -> None:
        event.stop()
        self.exit(event.providers)

    def action_cancel(self) -> None:
        wizard = self.query_one(ProviderWizard)
        if wizard.step == "key":
            wizard.show_pick()
            return
        self.exit(configured_provider_ids())


class ProviderOnboardScreen(ModalBase[tuple[str, ...]]):
    """In-session overlay for `/provider`."""

    CSS = PROVIDER_MODAL_CSS

    def __init__(
        self,
        workspace: str | Path,
        *,
        initial_provider: str | None = None,
    ) -> None:
        super().__init__()
        self.workspace = Path(workspace)
        self.initial_provider = initial_provider

    def compose(self) -> ComposeResult:
        with Container(id="provider-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield ProviderWizard(
                self.workspace,
                initial_provider=self.initial_provider,
            )

    def on_provider_wizard_completed(self, event: ProviderWizard.Completed) -> None:
        event.stop()
        self.dismiss(event.providers)

    def action_close_modal(self) -> None:
        wizard = self.query_one(ProviderWizard)
        if wizard.step == "key":
            wizard.show_pick()
            return
        self.dismiss(configured_provider_ids())
