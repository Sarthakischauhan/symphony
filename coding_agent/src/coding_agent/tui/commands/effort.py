"""Reasoning-effort policy for `/effort` and model capability."""

from __future__ import annotations

from typing import Any, Iterable

from core_ai import get_model
from coding_agent.tui.commands.catalog import EFFORT_CATALOG, EffortOption


def effort_matches(
    value: str,
    efforts: Iterable[EffortOption] = EFFORT_CATALOG,
) -> tuple[EffortOption, ...]:
    needle = value.strip().lower()
    return tuple(
        effort
        for effort in efforts
        if not needle
        or needle in effort.id.lower()
        or needle in effort.label.lower()
    )


def effort_options_for_model(model_id: str) -> tuple[EffortOption, ...]:
    """Return only effort levels advertised by the active model."""
    model = model_info(model_id)
    if model is None or not model.thinking_level_map:
        return ()

    supported = {
        "none" if level == "off" else level
        for level, provider_value in model.thinking_level_map
        if provider_value is not None
    }
    return tuple(
        option
        for option in EFFORT_CATALOG
        if option.id == "default" or option.id in supported
    )


def model_info(model_id: str):
    provider, separator, model_name = model_id.partition(":")
    if not separator:
        return None
    return get_model(provider, model_name)


def model_supports_effort(model_id: str) -> bool:
    return bool(effort_options_for_model(model_id))


def select_effort(app: Any, argument: str) -> None:
    value = argument.strip().lower()
    efforts = effort_options_for_model(app._agent.harness.model_id)
    supported = {option.id for option in efforts}
    if value not in supported:
        choices = ", ".join(option.id for option in efforts)
        app.add_notice(f"Unknown effort: {argument}. Choose: {choices}", "warning")
        return
    app._agent.harness.reasoning_effort = None if value == "default" else value
    label = next(option.label for option in efforts if option.id == value)
    app.add_notice(f"Reasoning effort set to {label}", "success")


def show_effort_picker(app: Any) -> None:
    efforts = effort_options_for_model(app._agent.harness.model_id)
    if not efforts:
        app.add_notice("The active model does not support effort settings.", "warning")
        return
    prompt = app.query_one("#prompt")
    prompt.value = "/effort "
    prompt.cursor_position = len(prompt.value)
    current = app._agent.harness.reasoning_effort or "default"
    app.query_one("#slash-menu").set_efforts(efforts, current)
