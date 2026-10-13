"""User addons from ``~/.symphony/addons`` merged into the coding agent."""

from coding_agent.addons.manager.bridge import AddonSurface, build_surface
from coding_agent.addons.manager.discovery import BUILTIN_ADDON_NAMES, load_user_addons, user_addons_root
from coding_agent.addons.manager.report import addons_report
from coding_agent.addons.manager.runtime import UserAddonRuntime
from coding_agent.addons.manager.tool_changes import tool_change_notice

__all__ = [
    "BUILTIN_ADDON_NAMES",
    "AddonSurface",
    "UserAddonRuntime",
    "addons_report",
    "build_surface",
    "load_user_addons",
    "tool_change_notice",
    "user_addons_root",
]
