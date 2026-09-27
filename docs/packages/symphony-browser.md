# symphony-browser

Browser-use agent for Symphony. Import it as `browser_agent`. Run it as
`symphony-browser`.

The goal is the user message of `CoreHarness.run`. The same chat model that
answers also calls the browser tools: `observe_page`, `click`, `type_text`,
`press_enter`, `select_option`, `scroll_down`, `scroll_up`, and `wait`. Each
tool acts on the open page and returns the new snapshot. When the model stops
calling tools, that message is `output_text`.

Jev is not this loop. An evaluation model returns a choice, not a tool call,
so it cannot drive the harness. The optional Jev finish check on
`symphony-code` (`--jev` / `/jev`) is unchanged and unrelated.

## Loop

```text
goal → CoreHarness.run
     → model calls a browser tool
     → tool returns the page (URL, title, numbered elements, text)
     → repeat until the model replies with no tool call
     → that reply is the answer
```

`--max-steps` is the harness turn cap. Hitting it ends the run as `limited`.
A model that stops without any text ends as `blocked`. A provider error ends
as `error`.

The model is whichever chat provider is configured, the same resolution as
`symphony` (`SYMPHONY_MODEL`, else the first configured provider). `--model
provider:model` overrides it. There is no separate text writer.

Secret fields (`type=password` or a credential `autocomplete`) are marked in
the page snapshot and their values never leave the browser. The model sees
`***` for a filled one and `""` for an empty one. A field named like a
password, PIN, OTP, or card is masked to `***` before the model sees it.

The goal is the harness prompt, so it is emitted and traced. Never put
credentials in it.

## Run it

```sh
uv sync
uv run --package symphony-browser playwright install chromium
uv run symphony-browser "Search for travel and report the price."
```

The command opens a DuckDuckGo HTML search for the query
(`https://html.duckduckgo.com/html/`) and lets the harness drive it. That
endpoint is static HTML, so a fresh Chromium is not sent to Google's
"this page was blocked" interstitial. DuckDuckGo can still rate-limit or show
a CAPTCHA; it does not block nothing. Pass `--url` to open a specific page.
The command exits if no chat provider is configured.

```sh
uv run --package symphony-browser symphony-browser \
  "Open the first article about espresso" \
  --url https://example.com
```

Only `http` and `https` URLs are accepted. `--trace trace.json` writes the run.
The Chromium sandbox is on; pass `--no-sandbox` only as root or in a
container. All flags: [CLI reference](../reference/cli.md#symphony-browser).

## Library

```python
import asyncio

from browser_agent import BrowserAgent
from browser_agent.session import PlaywrightBrowser

async def main() -> None:
    browser = PlaywrightBrowser()
    await browser.start()
    try:
        session = await browser.open("https://example.com")
        agent = BrowserAgent(max_steps=8)
        result = await agent.run("Open the espresso article.", session)
        print(result.status, result.output_text)
    finally:
        await browser.stop()

asyncio.run(main())
```

Tests mock the chat model and unset provider keys; they do not call
a live API. CI installs Chromium, so the end-to-end test runs there. Locally
it skips only when the Chromium binary is missing.
