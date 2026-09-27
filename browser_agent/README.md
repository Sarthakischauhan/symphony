# symphony-browser

Symphony browser-use agent. The core harness loop drives the page.

```sh
uv sync
uv run --package symphony-browser playwright install chromium
uv run symphony-browser "Search for travel and report the price."
```

Import as `browser_agent`. Command: `symphony-browser`.

The goal is the user message of `CoreHarness.run`. The chat model calls the
browser tools (`observe_page`, `click`, `type_text`, `press_enter`,
`select_option`, `scroll_down`, `scroll_up`, `wait`) and its last message,
the one with no tool call, is the answer.

Jev is not this loop. It returns a choice, not a tool call, so it cannot
drive the harness. The `symphony-code` finish check (`--jev`) is unchanged
and unrelated.

Full write-up: [docs/packages/symphony-browser.md](../docs/packages/symphony-browser.md).

The model is whichever chat provider is configured, the same resolution as
`symphony`. `--model provider:model` overrides it. Flags:
[docs/reference/cli.md](../docs/reference/cli.md#symphony-browser).

Do not put credentials in a goal: it is the harness prompt, so it is emitted
and traced.

Not published to PyPI. Workspace package only.
