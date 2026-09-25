"""Page sessions. The agent talks to this surface, not to Playwright directly.

``PlaywrightSession`` stamps ``data-jev-id`` on the live DOM and acts on those
nodes. Secret fields (``type=password`` or a credential ``autocomplete``) are
marked in the page, and only ``***`` (filled) or "" (empty) leaves it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol

from browser_agent.models import Decision, Element, Observation
from browser_agent.validate_url import require_http_url

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright

MAX_ELEMENTS = 60
MAX_PAGE_TEXT = 4000
MAX_OPTIONS = 12

_SNAPSHOT_JS = r"""
([maxElements, maxOptions, maxText]) => {
  document.querySelectorAll("[data-jev-id]").forEach((node) => node.removeAttribute("data-jev-id"));
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
  const nameOf = (el, secret) => {
    const bits = [
      el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.innerText,
      el.getAttribute("name"), el.getAttribute("alt"), el.getAttribute("title"),
    ];
    for (const bit of bits) {
      if (bit && bit.trim()) return bit.trim().replace(/\s+/g, " ").slice(0, 120);
    }
    return ((!secret && el.getAttribute("value")) || el.tagName || "").trim().slice(0, 120);
  };
  const out = [];
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "input" && ["hidden", "checkbox", "radio", "file"].includes(type)) continue;
    if (out.length >= maxElements) break;
    const clickOnly = tag === "input" && ["submit", "button", "image"].includes(type);
    const editable = !clickOnly && (
      tag === "textarea" || tag === "input" || el.isContentEditable ||
      ["textbox", "searchbox"].includes(el.getAttribute("role"))
    );
    const autocomplete = (el.getAttribute("autocomplete") || "").toLowerCase();
    const secret = type === "password" || /current-password|new-password|one-time-code|cc-/.test(autocomplete);
    const index = out.length + 1;
    el.setAttribute("data-jev-id", String(index));
    const role = el.getAttribute("role") || tag;
    const item = { index, role, name: nameOf(el, secret), value: "", kind: "click", options: [], secret };
    if (editable) {
      item.kind = "type";
      item.value = String(el.value || el.innerText || "").slice(0, 200);
    } else if (tag === "select") {
      item.kind = "select";
      item.value = String(el.value || "");
      item.options = Array.from(el.options || []).map((option) => option.label || option.text).slice(0, maxOptions);
    }
    if (secret) item.value = item.value ? "***" : "";
    out.push(item);
  }
  const text = (document.body ? document.body.innerText : "").replace(/\s+/g, " ").trim().slice(0, maxText);
  return { url: location.href, title: document.title || "", elements: out, text };
}
"""


class PageSession(Protocol):
    """One open page: observe it, then act on it with a gated Decision."""

    async def observe(self) -> Observation:
        """Snapshot the page for one step."""

    async def act(self, decision: Decision) -> None:
        """Run one gated decision on the page."""


def observation_from_payload(payload: dict[str, Any]) -> Observation:
    """Validate the snapshot object returned by ``_SNAPSHOT_JS``."""
    return Observation(
        url=str(payload.get("url") or ""),
        title=str(payload.get("title") or ""),
        elements=[Element.model_validate(item) for item in payload.get("elements") or []],
        text=str(payload.get("text") or ""),
    )


class PlaywrightSession:
    """A live Chromium page addressed through ``data-jev-id`` attributes."""

    def __init__(self, page: Page) -> None:
        self.page = page

    async def observe(self) -> Observation:
        """Snapshot the visible controls and page text."""
        payload = await self.page.evaluate(_SNAPSHOT_JS, [MAX_ELEMENTS, MAX_OPTIONS, MAX_PAGE_TEXT])
        if not isinstance(payload, dict):
            raise RuntimeError("page snapshot was not an object")
        return observation_from_payload(payload)

    async def act(self, decision: Decision) -> None:
        """Run the decision's operation on its target; ``type_value`` is the text to type."""
        target = self.page.locator(f'[data-jev-id="{decision.target_index()}"]')
        if decision.operation == "CLICK":
            await target.click(timeout=5000)
        elif decision.operation == "TYPE_TEXT":
            await target.fill(decision.type_value)
        elif decision.operation == "PRESS_ENTER":
            await target.press("Enter")
        elif decision.operation == "SELECT":
            await target.select_option(label=decision.select_option)
        elif decision.operation in {"SCROLL_DOWN", "SCROLL_UP"}:
            await self.page.mouse.wheel(0, 700 if decision.operation == "SCROLL_DOWN" else -700)
        elif decision.operation == "WAIT":
            await self.page.wait_for_timeout(300)
        await self.page.wait_for_timeout(50)


class PlaywrightBrowser:
    """Owns the Playwright process and one Chromium. Playwright is imported at launch."""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self, *, headless: bool = True, sandbox: bool = True) -> None:
        """Launch Chromium. ``sandbox=False`` is for root or containers only."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            chromium_sandbox=sandbox,
            args=[] if sandbox else ["--disable-dev-shm-usage"],
        )

    async def open(self, url: str) -> PlaywrightSession:
        """Open ``url`` (http or https only) in a new page."""
        require_http_url(url)
        if self._browser is None:
            raise RuntimeError("browser is not started")
        page = await self._browser.new_page(viewport={"width": 1100, "height": 800})
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        return PlaywrightSession(page)

    async def stop(self) -> None:
        """Close Chromium and Playwright; safe to call after a failed start."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


__all__ = [
    "MAX_ELEMENTS",
    "MAX_OPTIONS",
    "MAX_PAGE_TEXT",
    "PageSession",
    "PlaywrightBrowser",
    "PlaywrightSession",
    "observation_from_payload",
]
