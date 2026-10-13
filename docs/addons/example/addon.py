"""Example Symphony user addon: one tool, one command, one event handler.

Copy this folder to ~/.symphony/addons/example/ and run /reload.
"""

from core_harness import Tool
from core_harness.extensions import CommandSpec, ExtensionAPI

turns_seen = 0


def word_count(text: str) -> str:
    """Count the words in a piece of text."""
    return str(len(text.split()))


def _count_turn(event: str, payload: dict) -> None:
    global turns_seen
    turns_seen += 1


def _hello(argument: str) -> str:
    who = argument or "there"
    return f"Hello, {who}! The example addon has seen {turns_seen} turns."


_unsubscribe = None


def setup(api: ExtensionAPI) -> None:
    global _unsubscribe
    api.register_tool(Tool(word_count, name="example_word_count"))
    api.register_command(CommandSpec("hello", "Say hello from the example addon", _hello, "[name]"))
    _unsubscribe = api.on("turn_completed", _count_turn)


def dispose() -> None:
    if _unsubscribe is not None:
        _unsubscribe()
