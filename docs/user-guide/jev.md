# Jev critic mode

Optional evaluator on `symphony-code`. `--jev` / `/jev` turns on **critic
mode**. It is not a model switch: the main LLM stays the chat model, and Jev
never becomes primary.

The add-on is first-party (`coding_agent.evaluation.JevAddon`). It lives in
`coding_agent`, not `core_harness`. TypeSafe/Jev are not imported from the
harness.

## What Jev decides vs what it does not

v1 is **findings plus an optional in-thread note**. The evaluator answers a
fixed question set and the add-on stores structured findings (`decision` kind,
value, probs, label, short rationale). When `should_nudge` is true, `JevAddon`
injects **one** user-role critic note (`format_nudge`) into messages for the
next model turn. Prior Jev nudge markers are stripped so notes do not stack.

Symphony does **not**:

- auto-REPLAN or rewrite the todo/plan
- enter plan mode (`EnterPlanMode`)
- start a silent second `harness.run` (honour / follow-up defaults **off**)
- treat a bare boolean `True` / label as p=1.0 for actuation thresholds
- replace the chat/completions model with `typesafe-ai/jev`

Missing probabilities are a **weak signal**: enough to nudge, never enough to
honour or auto-run. Provider errors fail open (`skipped` / `error`); the run
still finishes.

`should_nudge` is true when findings show:

- conflicting `task_complete` + `remaining_work`
- `unsupported_claims`
- `next_action` in `continue` / `retry` / `replan` / `review` (`continue` on
  finish only)
- pre-task `needs_replan`

The note is a short template (plan or outcome incomplete, what Jev flagged,
suggested `next_action`, and that plan mode was not opened). Cap: at most one
nudge per phase.

### Start (`on_start`)

| Question | Kind |
| --- | --- |
| `plan_sufficient` | boolean |
| `needs_replan` | boolean |
| `next_action` | choice |

### Finish (`on_finish`)

| Question | Kind |
| --- | --- |
| `task_complete` | boolean |
| `remaining_work` | boolean |
| `unsupported_claims` | boolean |
| `next_action` | choice (`finish` / `continue` / `retry` / `review`) |

## Hook mapping

Evaluator methods are named so they are not mistaken for missing harness hooks.
The add-on implements only the existing `Addon` pair:

| Evaluator protocol | Addon hook | When |
| --- | --- | --- |
| `on_start` | `before_run` | Once at the start of `CoreHarness.run`; injects a note if `needs_replan` (or other start `should_nudge`) |
| `on_finish` | `after_run` | Once after a successful run; injects a note if `should_nudge` |

`before_turn` and `on_tool` are not overridden. Semantic state is rebuilt from
the run payload (request, plan items + status, observations, files modified,
last tool results, final text) with hard character caps. Every outbound text
field is run through `redact_secrets` (the same helper Langfuse uses) inside
the state builder before the gateway call. Raw transcripts and JSONL are
never dumped into the evaluator.

## Enable it

Off by default.

```sh
uv run --package symphony-code symphony --jev
```

In the TUI, `/jev` toggles critic mode (optional `on` / `off`). That is a mode
toggle, not `/model typesafe-ai/jev`. The setting is stored on
`evaluation.enabled` in `~/.symphony/config.json` and the agent reloads.

```json
{
  "evaluation": {
    "enabled": false,
    "honour_follow_up": false,
    "provider": "vercel",
    "model": "typesafe-ai/jev",
    "on_error": "fail-open",
    "brief_max_chars": 2000,
    "plan_max_chars": 2000,
    "final_max_chars": 4000
  }
}
```

`honour_follow_up` defaults to `false`. Leave it off: Jev will not consume a
follow-up or start a second harness run. `evaluation.enabled` also defaults
to `false`.

Calls go to Vercel AI Gateway `POST /v4/ai/evaluation-model` using the existing
helpers in `core_ai.providers.vercel` (`is_evaluation_model`,
`evaluation_request_body`, `evaluation_model_url`, headers). The chat base URL
is unchanged.

Without `AI_GATEWAY_API_KEY` / `VERCEL_AI_GATEWAY_API_KEY`, the evaluator
fail-opens (`skipped`). Tests use `MockEvaluator` / `StubEvaluator` and never
call a live API.
