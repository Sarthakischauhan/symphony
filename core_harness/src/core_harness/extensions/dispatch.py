"""Run addon event handlers and disposers, isolating each failure."""

from __future__ import annotations

import logging
from typing import Iterable

from core_harness.extensions.events import EventPayload
from core_harness.extensions.registry import AddonFailure, ExtensionSnapshot, LoadedAddon

logger = logging.getLogger(__name__)


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def dispatch_event(
    snapshot: ExtensionSnapshot, event: str, payload: EventPayload
) -> tuple[AddonFailure, ...]:
    """Call every active handler for ``event``. A raising handler only fails its own call."""
    failures: list[AddonFailure] = []
    for addon in snapshot.loaded:
        for subscription in addon.subscriptions:
            if not subscription.active or subscription.event != event:
                continue
            try:
                subscription.handler(event, payload)
            except Exception as exc:  # noqa: BLE001 - addon code is untrusted
                logger.warning("addon %s hook %s failed", addon.name, event, exc_info=True)
                failures.append(AddonFailure(addon.name, "hook", _error(exc)))
    return tuple(failures)


def dispose_addons(addons: Iterable[LoadedAddon]) -> tuple[AddonFailure, ...]:
    """Call each optional ``dispose``; turn off its handlers either way."""
    failures: list[AddonFailure] = []
    for addon in addons:
        for subscription in addon.subscriptions:
            subscription.cancel()
        if addon.dispose is None:
            continue
        try:
            addon.dispose()
        except Exception as exc:  # noqa: BLE001 - addon code is untrusted
            logger.warning("addon %s dispose failed", addon.name, exc_info=True)
            failures.append(AddonFailure(addon.name, "dispose", _error(exc)))
    return tuple(failures)


__all__ = ["dispatch_event", "dispose_addons"]
