# Jev finish check

Jev is an optional evaluator for `symphony-code`. It checks a completed run;
it does not replace the chat model or restrict tools while the agent works.

Enable it with `--jev`, `/jev on`, or set a rule for the current TUI session:

```text
/jev make sure the code being generated is not verbose and easy to follow
```

The rule remains active in that TUI session until you replace it or turn Jev
off with `/jev off`. It is not saved to `~/.symphony/config.json`. `/jev` with
no argument toggles the mode. `--jev` enables the finish check without a
session rule.

After each completed run, Jev sees a bounded, redacted summary of the request,
plan, tool observations, modified files, final answer, and the active rule.
It answers whether the task is complete, whether work remains, whether claims
need review, and whether the rule was satisfied. A rule violation requires an
explicit probability of at least 0.8; a bare boolean or label is not enough.

If Jev confidently finds a rule violation, Symphony asks the chat model to
revise the work to meet the rule. It permits **one automatic revision per user
task**, then stops to avoid a loop. Other finish findings may add a critic note
or request review. Without a rule, automatic follow-up remains off unless
`evaluation.honour_follow_up` is enabled explicitly.

Jev runs after the agent's work, so it does not block `bash`, edits, or other
tools. Evaluator errors and missing Vercel credentials fail open. The evaluator
uses `typesafe-ai/jev` through Vercel AI Gateway
`POST /v4/ai/evaluation-model` with `AI_GATEWAY_API_KEY` or
`VERCEL_AI_GATEWAY_API_KEY`.
