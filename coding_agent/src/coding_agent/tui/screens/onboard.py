"""First-run and in-session wizard for adding model provider credentials."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from coding_agent.credentials import save_provider_settings
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton
from coding_agent.tui.theme import ONBOARD_CSS, PROVIDER_MODAL_CSS, SYMPHONY_RICH_THEME
from core_ai.oauth import LoginCancelled, LoginFlow, save_token, start_login
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
        badge = spec.base_url_env if not spec.requires_key and spec.base_url_env else spec.env_key
        if spec.supports_oauth:
            badge = f"{badge} or subscription"
        content.append(f"   {badge}", style="#555555")
    else:
        content.append(spec.description, style="#737373")
    return Option(content, id=f"provider:{spec.id}")


def _continue_row(configured: tuple[str, ...]) -> Option:
    labels = ", ".join(get_provider(provider_id).label for provider_id in configured)
    content = Text("Continue")
    content.append("\n  ")
    content.append(f"Use {labels}", style="#737373")
    return Option(content, id="continue")


def _method_row(method_id: str, title: str, detail: str) -> Option:
    content = Text("› ")
    content.append(title)
    content.append("\n  ")
    content.append(detail, style="#737373")
    return Option(content, id=f"method:{method_id}")


def _oauth_methods(spec: ProviderSpec) -> list[Option]:
    if spec.id == "openai":
        oauth = _method_row("oauth", "Sign in with ChatGPT", "Use a ChatGPT Plus / Pro / Codex subscription")
    elif spec.id == "anthropic":
        oauth = _method_row("oauth", "Sign in with Claude", "Paste a setup-token or browser code")
    else:
        oauth = _method_row("oauth", "Sign in with xAI", "Device login for SuperGrok / Premium+")
    key_label = "Paste endpoint" if not spec.requires_key else "Paste API key"
    return [oauth, _method_row("key", key_label, spec.env_key if spec.requires_key else spec.description)]


class ProviderWizard(Vertical):
    """Pick a provider, choose sign-in vs key, then continue."""

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
        self.step: Literal["pick", "method", "key", "oauth"] = "pick"
        self._pending: str | None = None
        self._highlight_continue = False
        self._flow: LoginFlow | None = None
        self._oauth_done = False

    def compose(self) -> ComposeResult:
        yield Static("Add a provider", id="onboard-title")
        yield Static(
            "Choose where Symphony should send model calls. You can add more than one.",
            id="onboard-subtitle",
        )
        yield Static("", id="onboard-detail")
        yield OptionList(id="provider-list")
        yield Input(password=True, id="provider-key")
        yield Static("", id="onboard-error")
        yield Static(self._hint_text(), id="onboard-hint")

    def on_mount(self) -> None:
        self.query_one("#provider-key", Input).display = False
        self.query_one("#onboard-detail", Static).display = False
        if self.initial_provider:
            spec = get_provider(self.initial_provider)
            if spec.supports_oauth:
                self.show_method(self.initial_provider)
            else:
                self.show_key(self.initial_provider)
        else:
            self.show_pick()

    def show_pick(self) -> None:
        self._close_flow()
        self.step = "pick"
        self._pending = None
        self.query_one("#onboard-title", Static).update("Add a provider")
        self.query_one("#onboard-subtitle", Static).update(
            "Choose where Symphony should send model calls. You can add more than one."
        )
        self.query_one("#onboard-error", Static).update("")
        self.query_one("#onboard-detail", Static).update("")
        self.query_one("#onboard-detail", Static).display = False
        self.query_one("#provider-key", Input).display = False
        listing = self.query_one("#provider-list", OptionList)
        listing.display = True
        self._refresh_list()
        listing.focus()
        self._set_hint()

    def show_method(self, provider_id: str) -> None:
        spec = get_provider(provider_id)
        if not spec.supports_oauth:
            self.show_key(provider_id)
            return
        self._close_flow()
        self.step = "method"
        self._pending = provider_id
        self.query_one("#onboard-title", Static).update(spec.label)
        self.query_one("#onboard-subtitle", Static).update(
            "Sign in with a subscription, or paste an API key."
        )
        self.query_one("#onboard-error", Static).update("")
        self.query_one("#onboard-detail", Static).display = False
        self.query_one("#provider-key", Input).display = False
        listing = self.query_one("#provider-list", OptionList)
        listing.display = True
        listing.set_options(_oauth_methods(spec))
        listing.highlighted = 0
        listing.focus()
        self._set_hint()

    def show_key(self, provider_id: str) -> None:
        spec = get_provider(provider_id)
        self._close_flow()
        self.step = "key"
        self._pending = provider_id
        key_input = self.query_one("#provider-key", Input)
        if spec.requires_key:
            self.query_one("#onboard-title", Static).update(f"{spec.label} API key")
            self.query_one("#onboard-subtitle", Static).update(
                f"Paste a key from {spec.docs_url}"
            )
            key_input.password = True
            key_input.placeholder = spec.key_placeholder
        else:
            self.query_one("#onboard-title", Static).update(f"{spec.label} endpoint")
            self.query_one("#onboard-subtitle", Static).update(spec.description)
            key_input.password = False
            key_input.placeholder = spec.default_base_url or spec.key_placeholder
        self.query_one("#onboard-error", Static).update("")
        self.query_one("#onboard-detail", Static).display = False
        self.query_one("#provider-list", OptionList).display = False
        key_input.value = ""
        key_input.display = True
        key_input.focus()
        self._set_hint()

    def show_oauth(self, provider_id: str) -> None:
        self._close_flow()
        self.step = "oauth"
        self._pending = provider_id
        self._oauth_done = False
        try:
            flow = start_login(provider_id)
        except Exception as exc:
            self.show_method(provider_id)
            self.query_one("#onboard-error", Static).update(str(exc))
            return
        self._flow = flow
        prompt = flow.prompt
        self.query_one("#onboard-title", Static).update(prompt.title)
        if prompt.user_code:
            self.query_one("#onboard-subtitle", Static).update(f"Code: {prompt.user_code}")
        else:
            self.query_one("#onboard-subtitle", Static).update("Finish in the browser, or paste below.")
        detail_parts = [prompt.instructions]
        if prompt.url:
            detail_parts.append(prompt.url)
        detail_widget = self.query_one("#onboard-detail", Static)
        detail_widget.update("\n".join(detail_parts))
        detail_widget.display = True
        self.query_one("#onboard-error", Static).update("")
        self.query_one("#provider-list", OptionList).display = False
        key_input = self.query_one("#provider-key", Input)
        if prompt.kind == "device":
            key_input.display = False
        else:
            key_input.password = False
            key_input.placeholder = prompt.paste_hint
            key_input.value = ""
            key_input.display = True
            key_input.focus()
        self._set_hint()
        self.app.run_worker(self._wait_oauth(), exclusive=True)

    def finish(self) -> None:
        self._close_flow()
        self.post_message(self.Completed(configured_provider_ids()))

    def cancel(self) -> bool:
        """Handle Escape. Returns True when the host should close."""
        if self.step == "oauth":
            pending = self._pending
            self._close_flow()
            if pending:
                self.show_method(pending)
            else:
                self.show_pick()
            return False
        if self.step == "key":
            pending = self._pending
            if pending and get_provider(pending).supports_oauth:
                self.show_method(pending)
            else:
                self.show_pick()
            return False
        if self.step == "method":
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
            provider_id = option_id.split(":", 1)[1]
            spec = get_provider(provider_id)
            if spec.supports_oauth:
                self.show_method(provider_id)
            else:
                self.show_key(provider_id)
            return
        if option_id == "method:oauth" and self._pending:
            self.show_oauth(self._pending)
            return
        if option_id == "method:key" and self._pending:
            self.show_key(self._pending)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self.step == "oauth":
            self._submit_oauth_paste(event.value)
            return
        if self._pending is None or self.step != "key":
            return
        spec = get_provider(self._pending)
        try:
            if spec.requires_key:
                save_provider_settings(self._pending, api_key=event.value)
            else:
                save_provider_settings(self._pending, base_url=event.value)
        except ValueError as exc:
            self.query_one("#onboard-error", Static).update(str(exc))
            return
        self._highlight_continue = True
        self.show_pick()

    def _submit_oauth_paste(self, pasted: str) -> None:
        if self._flow is None:
            return
        try:
            token = self._flow.complete_from_paste(pasted)
        except ValueError as exc:
            self.query_one("#onboard-error", Static).update(str(exc))
            return
        except Exception as exc:
            self.query_one("#onboard-error", Static).update(str(exc))
            return
        self._finish_oauth(token)

    async def _wait_oauth(self) -> None:
        flow = self._flow
        if flow is None:
            return
        try:
            token = await asyncio.to_thread(flow.wait)
        except LoginCancelled:
            return
        except Exception as exc:
            self._oauth_failed(str(exc))
            return
        self._finish_oauth(token)

    def _oauth_failed(self, message: str) -> None:
        if self.step != "oauth":
            return
        self.query_one("#onboard-error", Static).update(message)

    def _finish_oauth(self, token: object) -> None:
        if self._oauth_done or self.step != "oauth" or self._pending is None:
            return
        from core_ai.oauth.types import OAuthToken

        if not isinstance(token, OAuthToken):
            return
        self._oauth_done = True
        save_token(self._pending, token)
        self._close_flow()
        self._highlight_continue = True
        self.show_pick()

    def _close_flow(self) -> None:
        flow = self._flow
        self._flow = None
        if flow is not None:
            flow.close()

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
        if self.step == "oauth":
            if self._flow is not None and self._flow.prompt.kind == "device":
                return "Approve in the browser   Esc back"
            return "Enter paste code   Esc back"
        if self.step == "method":
            return "↑↓ select   Enter continue   Esc back"
        if self.step == "key":
            if self._pending and not get_provider(self._pending).requires_key:
                spec = get_provider(self._pending)
                if spec.default_base_url:
                    return "Enter save (blank uses default)   Esc back"
                return "Enter save   Esc back"
            return "Enter save   Esc back"
        close = "skip" if self.first_run else "close"
        if configured_provider_ids():
            return f"↑↓ select   Enter add   Continue starts   Esc {close}"
        return f"↑↓ select   Enter add   Esc {close}"

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
        if not wizard.cancel():
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
        if not wizard.cancel():
            return
        self.dismiss(configured_provider_ids())
