"""In-process stand-ins shared by the browser tests."""

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


class StaticTextWriter:
    """Always writes the same string."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def write(self, *, goal: str, element: Element, observation: Observation) -> str:
        del goal, element, observation
        self.calls += 1
        return self.text


def _answer(operation: str, probability: float, goal_met: float, **targets: str) -> dict:
    answers = {name: {"type": "choice", "choice": value} for name, value in targets.items()}
    answers["operation"] = {"type": "choice", "choice": operation, "probabilities": {operation: probability}}
    answers["goal_met"] = {"type": "boolean", "probability": goal_met}
    return {"model": "typesafe-ai/jev", "answers": answers}


class ScriptedJev:
    """Speaks the evaluation-model answer schema for the catalog task on any catalog page."""

    def __init__(self) -> None:
        self.states: list[dict] = []
        self.questions: list[dict] = []

    async def complete(self, state: dict, questions: dict) -> dict:
        self.states.append(state)
        self.questions.append(questions)
        if "$18" in state["page_text"]:
            return _answer("DONE", 0.96, 0.97)
        elements = state["elements"]
        field = next((element for element in elements if element["kind"] == "type"), None)
        if field is not None and not field["value"]:
            return _answer("TYPE_TEXT", 0.93, 0.04, type_target=str(field["index"]), type_value="travel")
        button = next(e for e in elements if e["kind"] == "click" and "search" in e["name"].lower())
        return _answer("CLICK", 0.91, 0.08, click_target=str(button["index"]))


class AnswerJev:
    """Returns the same answers for every request and records each state."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.states: list[dict] = []

    async def complete(self, state: dict, questions: dict) -> dict:
        del questions
        self.states.append(state)
        return {"answers": self.answers}
