"""Page sessions. The agent talks to this surface, not to Playwright directly.

``MemorySession`` is the in-process page used by tests. ``PlaywrightSession``
stamps ``data-jev-id`` on the live DOM and clicks those nodes.
"""

from __future__ import annotations

from typing import Any, Protocol

from browser_agent.models import Decision, Element, Observation

_SNAPSHOT_JS = r"""
() => {
  document.querySelectorAll("[data-jev-id]").forEach((node) => {
    node.removeAttribute("data-jev-id");
  });
  const selector = [
    "a", "button", "input", "textarea", "select", "summary",
    "[role='button']", "[role='link']", "[role='textbox']",
    "[role='searchbox']", "[role='combobox']", "[contenteditable='true']"
  ].join(",");
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const nameOf = (el) => {
    const bits = [
      el.getAttribute("aria-label"),
      el.getAttribute("placeholder"),
      el.innerText,
      el.getAttribute("name"),
      el.getAttribute("alt"),
      el.getAttribute("title"),
    ];
    for (const bit of bits) {
      if (bit && bit.trim()) return bit.trim().replace(/\s+/g, " ").slice(0, 120);
    }
    return (el.getAttribute("value") || el.tagName || "").trim().slice(0, 120);
  };
  const out = [];
  let index = 0;
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "input" && ["hidden", "checkbox", "radio", "file"].includes(type)) continue;
    const clickOnly = tag === "input" && ["submit", "button", "image"].includes(type);
    const editable = !clickOnly && (
      tag === "textarea" ||
      (tag === "input" && !["submit", "button", "image"].includes(type)) ||
      el.isContentEditable ||
      el.getAttribute("role") === "textbox" ||
      el.getAttribute("role") === "searchbox"
    );
    const dropdown = tag === "select";
    index += 1;
    if (index > 60) break;
    el.setAttribute("data-jev-id", String(index));
    let kind = "click";
    let value = "";
    let options = [];
    if (editable) {
      kind = "type";
      value = String(el.value || el.innerText || "").slice(0, 200);
    } else if (dropdown) {
      kind = "select";
      value = String(el.value || "");
      options = Array.from(el.options || []).map((option) => option.label || option.text).slice(0, 12);
    }
    out.push({
      index,
      role: el.getAttribute("role") || tag,
      name: nameOf(el),
      value,
      kind,
      options,
    });
  }
  const text = (document.body ? document.body.innerText : "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 4000);
  return { url: location.href, title: document.title || "", elements: out, text };
}
"""


class PageSession(Protocol):
    async def observe(self) -> Observation:
        ...

    async def act(self, decision: Decision, text: str) -> None:
        ...

    async def close(self) -> None:
        ...


def observation_from_payload(payload: dict[str, Any]) -> Observation:
    elements = [Element.model_validate(item) for item in payload.get("elements") or []]
    return Observation(
        url=str(payload.get("url") or ""),
        title=str(payload.get("title") or ""),
        elements=elements,
        text=str(payload.get("text") or ""),
    )


class MemorySession:
    """Tiny catalog page: type a query, click Search, a price appears."""

    def __init__(self, *, url: str = "https://books.example/catalog") -> None:
        self.url = url
        self.title = "Symphony Books"
        self.query = ""
        self.submitted = False
        self.opened = ""

    async def observe(self) -> Observation:
        elements = [
            Element(index=1, role="textbox", name="Search books", value=self.query, kind="type"),
            Element(index=2, role="button", name="Search", kind="click"),
        ]
        text = "Symphony Books. Search the catalog."
        if self.submitted and "travel" in self.query.lower():
            text += " The Alps Guide — $18 — A travel guide to alpine huts."
        elif self.submitted:
            text += " No matches."
        if self.opened:
            text += f" Opened {self.opened}."
        return Observation(url=self.url, title=self.title, elements=elements, text=text)

    async def act(self, decision: Decision, text: str) -> None:
        if decision.operation == "TYPE_TEXT":
            self.query = text
        elif decision.operation == "CLICK" and decision.click_target == 2:
            self.submitted = True
        elif decision.operation == "PRESS_ENTER":
            self.submitted = True
        elif decision.operation == "CLICK":
            element_name = "result"
            self.opened = element_name

    async def close(self) -> None:
        return None


class PlaywrightSession:
    def __init__(self, page: Any) -> None:
        self.page = page

    async def observe(self) -> Observation:
        payload = await self.page.evaluate(_SNAPSHOT_JS)
        if not isinstance(payload, dict):
            raise RuntimeError("page snapshot was not an object")
        return observation_from_payload(payload)

    async def act(self, decision: Decision, text: str) -> None:
        if decision.operation == "CLICK" and decision.click_target is not None:
            await self.page.locator(f'[data-jev-id="{decision.click_target}"]').click(timeout=5000)
        elif decision.operation == "TYPE_TEXT" and decision.type_target is not None:
            field = self.page.locator(f'[data-jev-id="{decision.type_target}"]')
            await field.fill("")
            if text:
                await field.fill(text)
        elif decision.operation == "PRESS_ENTER" and decision.type_target is not None:
            await self.page.locator(f'[data-jev-id="{decision.type_target}"]').press("Enter")
        elif decision.operation == "SELECT" and decision.select_index is not None:
            await self.page.locator(f'[data-jev-id="{decision.select_index}"]').select_option(
                label=decision.select_option
            )
        elif decision.operation == "SCROLL_DOWN":
            await self.page.mouse.wheel(0, 700)
        elif decision.operation == "SCROLL_UP":
            await self.page.mouse.wheel(0, -700)
        elif decision.operation == "WAIT":
            await self.page.wait_for_timeout(300)
        await self.page.wait_for_timeout(50)

    async def close(self) -> None:
        return None


class PlaywrightBrowser:
    """Owns the Playwright process. Import of playwright is deferred to launch."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None

    async def start(self, *, headless: bool = True) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    async def open(self, url: str) -> PlaywrightSession:
        if self._browser is None:
            raise RuntimeError("browser is not started")
        page = await self._browser.new_page(viewport={"width": 1100, "height": 800})
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        return PlaywrightSession(page)

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


__all__ = [
    "MemorySession",
    "PageSession",
    "PlaywrightBrowser",
    "PlaywrightSession",
    "observation_from_payload",
]
