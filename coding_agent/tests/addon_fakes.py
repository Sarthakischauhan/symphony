"""An empty user-addon runtime for test doubles that stand in for CodingAgent."""

from core_harness.extensions import EMPTY_SNAPSHOT

from coding_agent.extensions import UserAddonRuntime


def no_user_addons() -> UserAddonRuntime:
    return UserAddonRuntime(builtin_tool_names=(), loader=lambda _names: EMPTY_SNAPSHOT)
