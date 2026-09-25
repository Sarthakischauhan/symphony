# symphony-browser

Browser-use agent for Symphony. Import it as `browser_agent`. Run it as
`symphony-browser`.

Jev is the policy. It is an evaluation model: one forward pass, a choice
over the options you listed, and a probability for each option. It does not
write the next action as prose and it does not invent an element that was
not on the page.

This is separate from the optional Jev finish check on `symphony-code`
(`--jev` / `/jev`). That critic runs after a coding agent. Here Jev decides
every browser step.

## Loop

```text
page → numbered element table
     → one Jev request
         operation
         click_target
         type_target
         select_target
         type_value, when the goal already contains the string
         goal_met
     → code runs only the target that matches the operation
     → repeat until DONE, BLOCKED, or the step cap
```

Operations: `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`,
`WAIT`, `PRESS_ENTER`, `DONE`, `BLOCKED`. An operation is offered only when
the page has a control that can perform it.

The chat harness loop is not the decider. An evaluation response cannot
carry free tool arguments, so a tool call of `{}` would hide which element
was chosen. `BrowserAgent` still emits through `CoreHarness.emit`, which
stamps `run_id`, `session_id`, `agent_id`, and `jev_decision` for any UI
on the control plane.

A chat model runs only when the operation is `TYPE_TEXT` and the goal did
not already contain the string (a quote, or the phrase after "search for").
With `XAI_API_KEY` set, that model is Grok (`grok-4.5` unless
`--text-model grok:<id>` overrides it). Password fields are typed, but the
event stores `***`.

## Credentials

First match, unless `SYMPHONY_JEV_PROVIDER` is `vercel`, `typesafe`, or
`openrouter`:

| Provider | Key | Model | Endpoint |
| --- | --- | --- | --- |
| Vercel AI Gateway | `AI_GATEWAY_API_KEY` or `VERCEL_AI_GATEWAY_API_KEY` | `typesafe-ai/jev` | `POST /v4/ai/evaluation-model` |
| TypeSafe | `TYPESAFE_API_KEY` | `jev-latest` | `https://api.typesafe.ai/v1/systemone` |
| OpenRouter | `OPENROUTER_API_KEY` | `~typesafe/jev-latest` | `https://openrouter.ai/api/alpha/decisions` |

`JEV_MODEL` overrides the model id. The Vercel path reuses
`core_ai.providers.vercel_evaluation`, the same helper as the coding-agent
critic.

## Run the demo

```sh
uv sync
uv run --package symphony-browser playwright install chromium
uv run --package symphony-browser symphony-browser demo
```

The demo serves a one-page catalog on localhost and asks the agent to
search for "travel" and report the price of The Alps Guide. With a Jev key,
Jev chooses each step. Without one, the command says so and uses an offline
fixture policy. That fixture is not an evaluation model; events record
`provider: fixture`.

```sh
uv run --package symphony-browser symphony-browser run \
  --url https://example.com \
  --goal "Open the first article about espresso"
```

Only `http` and `https` URLs are accepted. `--policy jev` fails instead of
falling back when the key is missing. `--trace trace.json` writes the run.

## Library

```python
import asyncio

from browser_agent import BrowserAgent, build_policy
from browser_agent.session import PlaywrightBrowser

async def main() -> None:
    browser = PlaywrightBrowser()
    await browser.start()
    try:
        session = await browser.open("https://example.com")
        agent = BrowserAgent(build_policy("jev"), max_steps=8)
        result = await agent.run("Open the espresso article.", session)
        print(result.status, result.output_text)
    finally:
        await browser.stop()

asyncio.run(main())
```

Tests mock the evaluation response. They do not call a live API. The
Chromium test skips when the browser binary is not installed.
