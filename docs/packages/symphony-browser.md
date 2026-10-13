# symphony-browser

A browser-use agent that combines `core_harness` with a Chromium-backed browser session. The harness coordinates model turns; browser actions are exposed as tools. Import the package as `browser_agent`.

**Availability:** workspace-only and not currently published on PyPI. Install the workspace and Chromium using the [installation guide](../getting-started/installation.md) and commands below.

## Run a task

```sh
uv run --package symphony-browser playwright install chromium
uv run --package symphony-browser symphony-browser \
  "Open the first article about espresso" --url https://example.com
```

Without `--url`, the agent opens a DuckDuckGo HTML search for the task. Only HTTP and HTTPS URLs are accepted. The Chromium sandbox is enabled by default; `--no-sandbox` should only be used where necessary, such as a root container.

## Use the library

```python
import asyncio
from browser_agent import BrowserAgent
from browser_agent.session import PlaywrightBrowser

async def main() -> None:
    browser = PlaywrightBrowser()
    await browser.start()
    try:
        session = await browser.open("https://example.com")
        result = await BrowserAgent(max_steps=8).run(
            "Open the espresso article.", session
        )
        print(result.status, result.output_text)
    finally:
        await browser.stop()

asyncio.run(main())
```

The task is sent through the harness and may be included in events or an optional trace; never put credentials in it. Browser tools only expose a limited observation/action surface, but website content remains untrusted input. Read the [CLI reference](../reference/cli.md#symphony-browser) and [environment reference](../reference/environment.md#browser-agent-symphony-browser) for options and provider configuration.
