# symphony-browser

Symphony browser-use agent. Jev chooses every action. A chat model writes
text only when a field has to be typed.

```sh
uv sync
uv run --package symphony-browser playwright install chromium
uv run --package symphony-browser symphony-browser demo
```

Import as `browser_agent`. Command: `symphony-browser`.

Jev is TypeSafe's evaluation model (`typesafe-ai/jev` on Vercel AI Gateway,
or `jev-latest` on the TypeSafe and OpenRouter decision APIs). Each step
posts one question set: the operation, and a speculative target for click,
type, and select. Code executes only the target that matches the chosen
operation. The page is a numbered element table from the DOM, not a
screenshot.

This is not the `symphony-code` finish check (`--jev`). That critic runs
after a coding agent. Here Jev is the policy inside the loop.

Full write-up: [docs/packages/symphony-browser.md](../docs/packages/symphony-browser.md).

| Key | What it drives |
| --- | --- |
| `AI_GATEWAY_API_KEY` or `VERCEL_AI_GATEWAY_API_KEY` | `typesafe-ai/jev` via `POST /v4/ai/evaluation-model` |
| `TYPESAFE_API_KEY` | `jev-latest` via `https://api.typesafe.ai/v1/systemone` |
| `OPENROUTER_API_KEY` | `~typesafe/jev-latest` via OpenRouter decisions |
| `XAI_API_KEY` | Grok, only when `TYPE_TEXT` needs a string the goal did not already contain |

Do not put credentials in a goal: it is emitted, sent to Jev, and traced.
Flags: [docs/reference/cli.md](../docs/reference/cli.md#symphony-browser).

Set `SYMPHONY_JEV_PROVIDER` to `vercel`, `typesafe`, or `openrouter` when
more than one key is present. The default is the Vercel gateway, which is
how the rest of Symphony already calls Jev.

Without a Jev key, `symphony-browser demo` says so and uses an offline
fixture policy. That policy is not Jev. Pass `--policy jev` to require the
evaluation model.

Not published to PyPI. Workspace package only.
