"""User extensions: addons that register tools, commands and event handlers.

``loader.load_addons`` builds an immutable ``ExtensionSnapshot`` from addon
folders. The harness owns no product paths: callers pass the roots.
"""

from core_harness.extensions.api import CommandHandler, CommandSpec, ExtensionAPI, ToolSpec
from core_harness.extensions.dispatch import dispatch_event, dispose_addons
from core_harness.extensions.events import ADDON_EVENTS, AddonEvent, EventHandler, EventPayload
from core_harness.extensions.loader import load_addons
from core_harness.extensions.manifest import AddonManifest, read_manifest
from core_harness.extensions.registry import (
    EMPTY_SNAPSHOT,
    AddonFailure,
    ExtensionSnapshot,
    LoadedAddon,
    Subscription,
)

__all__ = [
    "ADDON_EVENTS",
    "AddonEvent",
    "AddonFailure",
    "AddonManifest",
    "CommandHandler",
    "CommandSpec",
    "EMPTY_SNAPSHOT",
    "EventHandler",
    "EventPayload",
    "ExtensionAPI",
    "ExtensionSnapshot",
    "LoadedAddon",
    "Subscription",
    "ToolSpec",
    "dispatch_event",
    "dispose_addons",
    "load_addons",
    "read_manifest",
]
