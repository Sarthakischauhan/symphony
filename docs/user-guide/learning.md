# Learning

Learning is enabled by default. After a successful run, the harness
`after_run` hook starts a background reflection: one structured model call
capped at 900 output tokens. The reviewer returns durable lessons **and** a
two-line recap. The recap is emitted as `run_summary` and shown in the agent
transcript as **summary so far**. Useful lessons are appended to
`<workspace>/.symphony/learning/lessons.jsonl`.

Reflection never delays or changes the completed run. Future runs receive only
a small task-relevant selection of lessons. Routine runs can return
`should_save=false` and still show a recap. Reflection failures are logged
without affecting the agent. Plan mode skips reflection.

## Disable it

- `"learning": {"enabled": false}` in the spawn settings file.
- `enable_learning=False` on the agent.
- `symphony --no-learning` on the TUI.

## Shutdown

Call `await agent.shutdown_learning()` (or `wait_for_learning()`) when an
application needs to cancel or drain pending reflection before exit. The TUI
does this automatically. `/learning` opens markdown-rendered lessons.

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Run reflection after successful turns |
| `max_output_tokens` | `900` | Cap on the reflection call |
| `max_lessons` | `200` | Store size |
| `context_limit` | `6` | How many lessons are injected later |
| `context_max_chars` | `1400` | Injected-lesson budget |
