"""Browser tools the harness model can call."""

from core_harness import Tool

from browser_agent.session import PageSession
from browser_agent.tools.click import ClickTool
from browser_agent.tools.observe import ObservePageTool
from browser_agent.tools.press_enter import PressEnterTool
from browser_agent.tools.scroll import ScrollTool
from browser_agent.tools.select import SelectTool
from browser_agent.tools.type_text import TypeTextTool
from browser_agent.tools.wait import WaitTool

__all__ = [
    "ClickTool",
    "ObservePageTool",
    "PressEnterTool",
    "ScrollTool",
    "SelectTool",
    "TypeTextTool",
    "WaitTool",
    "browser_tools",
]


def browser_tools(session: PageSession) -> list[Tool]:
    """Every browser action the harness model can call on ``session``."""
    return [
        ObservePageTool(session),
        ClickTool(session),
        TypeTextTool(session),
        PressEnterTool(session),
        SelectTool(session),
        ScrollTool(session, down=True),
        ScrollTool(session, down=False),
        WaitTool(session),
    ]
