# Jev completion checks

Jev is an optional evaluator for a completed Symphony Code run. It checks the result against a rule you provide; it is not a tool-approval system and does not replace human review.

## Enable it

Start the TUI with `--jev`, or use `/jev` during a session. `/jev <rule>` sets a completion rule for that TUI session. For example, ask it to verify that a test passes or that a named file exists.

The evaluator uses Vercel AI Gateway credentials and a Jev evaluation model. Configure `AI_GATEWAY_API_KEY` (or `VERCEL_AI_GATEWAY_API_KEY`) as described in the [environment reference](../reference/environment.md#jev-critic-optional). Missing credentials fail open: the evaluation is skipped rather than blocking the completed run.

A confident rule violation can trigger one automatic revision attempt. With no rule, follow-up remains off by default. Normal coding-agent approval prompts still apply to that revision.

## When to use it

Use Jev for a narrow, observable completion condition—not as proof that a change is correct. Inspect the actual diff and run relevant tests yourself. See [Configuration](./configuration.md) and the [CLI reference](../reference/cli.md#symphony-terminal-ui).
