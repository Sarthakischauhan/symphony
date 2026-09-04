"""Provider onboarding policy for the `/provider` command."""

from __future__ import annotations

from typing import Any

from core_ai import find_provider, get_provider
from core_ai.providers.catalog import PROVIDERS, configured_provider_ids
from coding_agent.credentials import OFFLINE_HINT
from coding_agent.tui.screens import ProviderOnboardScreen


def open_provider_onboard(app: Any, argument: str = "") -> None:
    initial = None
    if argument:
        selected = find_provider(argument)
        if selected is None:
            app.add_notice(
                f"Unknown provider: {argument}. Choose {', '.join(spec.id for spec in PROVIDERS)}.",
                "warning",
            )
            return
        initial = selected.id
    app.push_screen(
        ProviderOnboardScreen(app.workspace, initial_provider=initial),
        lambda providers: on_provider_onboard(app, providers),
    )


def on_provider_onboard(app: Any, _providers: tuple[str, ...] | None) -> None:
    current = set(configured_provider_ids())
    previous = set(app._agent.registry.namespaces()) if app._agent is not None else set()
    if not current:
        if app._agent is None:
            app.add_notice(OFFLINE_HINT, "warning")
        return
    if current == previous:
        app.query_one("#prompt").focus()
        return
    app.run_worker(reload_after_provider(app), exclusive=False)


async def reload_after_provider(app: Any) -> None:
    from coding_agent.tui.commands.manager import reload_project

    await reload_project(app)
    current = configured_provider_ids()
    if not current:
        return
    labels = ", ".join(get_provider(provider_id).label for provider_id in current)
    app.add_notice(f"Providers ready · {labels}. Use /model to switch.", "success")
