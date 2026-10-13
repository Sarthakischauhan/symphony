# symphony-browser

A browser-use agent built on Symphony's Python harness. It opens a page in Chromium, exposes browser actions as tools, and returns the model's final response. Import it as `browser_agent`.

**Availability:** workspace package only; it is not currently published on PyPI. See the [source installation guide](../docs/getting-started/installation.md).

## Run it from the workspace

```sh
uv sync
uv run --package symphony-browser playwright install chromium
uv run --package symphony-browser symphony-browser "Open the first article about espresso" --url https://example.com
```

The default search opens DuckDuckGo. Only HTTP and HTTPS URLs are accepted. Do not include credentials in a prompt: the task is recorded in events and optional traces. Browser content is untrusted input; review actions and outputs.

## Build with the library

See the [browser agent guide](../docs/packages/symphony-browser.md) for a library example, tool behavior, and limitations. The [CLI reference](../docs/reference/cli.md#symphony-browser) lists command options.
