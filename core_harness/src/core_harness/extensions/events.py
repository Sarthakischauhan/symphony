"""Events an addon can subscribe to with ``api.on(event, handler)``.

The names are the harness control-plane event names; addons observe the
same stream a UI does. Handlers are read-only and run inline, so they must
return quickly. A handler that raises is isolated to that one call.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from core_harness.models import ControlPlaneEventType

AddonEvent = ControlPlaneEventType
ADDON_EVENTS: frozenset[str] = frozenset(event.value for event in ControlPlaneEventType)

EventPayload = Mapping[str, Any]
EventHandler = Callable[[str, EventPayload], None]

__all__ = ["ADDON_EVENTS", "AddonEvent", "EventHandler", "EventPayload"]
