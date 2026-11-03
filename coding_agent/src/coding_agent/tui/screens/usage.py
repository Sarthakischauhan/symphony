"""Provider-reported subscription usage modal."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from rich.text import Text
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static

from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from core_ai.providers.catalog import configured_provider_ids, get_provider
from core_ai.quota import QuotaResult, quota_service


def _window_label(label: str) -> str:
    label = re.sub(r"^codex\s*·\s*", "", label, flags=re.IGNORECASE)
    label = re.sub(r"\b(?:five|5) hours?\b", "5 hours", label, flags=re.IGNORECASE)
    label = re.sub(r"\b(?:seven|7) days?\b", "7 days", label, flags=re.IGNORECASE)
    if label.startswith("7 days ") and " · " not in label:
        label = "7 days · " + label[len("7 days "):]
    return label


def _reset_label(reset: datetime, now: datetime) -> str:
    seconds = (reset - now).total_seconds()
    if seconds <= 0:
        return "reset time passed"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = int(seconds // size)
            return f"resets in {count} {unit}{'s' if count != 1 else ''}"
    return "resets in less than a minute"


class UsageScreen(ModalBase[None]):
    CSS = """
    UsageScreen { align: center middle; background: #000000 60%; }
    #usage-pane { width: 80%; max-width: 90; height: 75%; border: round #484F58; background: #0A0A0A; padding: 1 2; }
    #usage-title { height: 2; text-style: bold; }
    #usage-body { height: 1fr; }
    #usage-hint { height: 1; color: #737373; }
    """
    BINDINGS = [*ModalBase.BINDINGS, Binding("r", "refresh_usage", "Refresh", show=False, priority=True)]

    def compose(self):
        with Container(id="usage-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static("Provider usage", id="usage-title")
            with ModalScroll(id="usage-body"):
                yield Static("Loading provider usage…", id="usage-results", markup=False)
            yield Static("R refresh   ·   Esc close", id="usage-hint")

    def on_mount(self) -> None:
        self._load(False)

    def action_refresh_usage(self) -> None:
        self._load(True)

    def _load(self, refresh: bool) -> None:
        self.query_one("#usage-results", Static).update("Loading provider usage…")
        self.run_worker(self._fetch(refresh), group="usage", exclusive=True)

    async def _fetch(self, refresh: bool) -> None:
        providers = configured_provider_ids()
        results = await asyncio.gather(*(quota_service.get(provider, refresh=refresh) for provider in providers))
        if not self.is_mounted:
            return
        self.query_one("#usage-results", Static).update(self._format(results))

    @staticmethod
    def _format(results: list[QuotaResult]) -> Text:
        if not results:
            return Text("No providers configured. Use /login to add one.")
        text = Text()
        now = datetime.now(timezone.utc)
        for index, result in enumerate(results):
            if index:
                text.append("\n\n")
            text.append(get_provider(result.provider).label, style="bold")
            if result.message:
                text.append(f"\n  {result.message}", style="#737373")
            for window in result.windows:
                label = _window_label(window.label)
                color = "#b49ad8" if "5 hours" in label.lower() else "#c7b66e" if "7 days" in label.lower() or "weekly" in label.lower() else "#738794"
                filled = round(max(0, min(window.used_percent, 100)) * 22 / 100)
                text.append(f"\n\n{label}\n")
                text.append("█" * filled, style=color)
                text.append("░" * (22 - filled), style="#484f58")
                text.append(f"  {window.used_percent:g}% used")
                if window.resets_at:
                    text.append(f" · {_reset_label(window.resets_at, now)}", style="#737373")
        return text
