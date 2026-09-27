"""In-process stand-in for a page, shared by the browser tests."""

from __future__ import annotations

from browser_agent.models import Decision, Element, Observation


class MemorySession:
    """Tiny catalog page: type a query, click Search, a price appears."""

    def __init__(self, *, url: str = "https://books.example/catalog") -> None:
        self.url = url
        self.query = ""
        self.submitted = False

    async def observe(self) -> Observation:
        text = "Symphony Books. Search the catalog."
        if self.submitted and "travel" in self.query:
            text += " The Alps Guide — $18 — A travel guide to alpine huts."
        return Observation(
            url=self.url,
            title="Symphony Books",
            text=text,
            elements=[
                Element(index=1, role="textbox", name="Search books", value=self.query, kind="type"),
                Element(index=2, role="button", name="Search", kind="click"),
            ],
        )

    async def act(self, decision: Decision) -> None:
        if decision.operation == "TYPE_TEXT":
            self.query = decision.type_value
        elif decision.operation == "PRESS_ENTER" or (decision.operation == "CLICK" and decision.click_target == 2):
            self.submitted = True
