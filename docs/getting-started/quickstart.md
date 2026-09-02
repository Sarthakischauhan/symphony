# Quickstart

Get one clean conversation working before you change config, spawn subagents,
or wire the HTTP server.

## 1. Set a key and launch

```sh
export OPENAI_API_KEY=sk-...
uv run --package symphony-code symphony
```

The default workspace is the current directory. Point it somewhere else with
`--workspace`:

```sh
uv run --package symphony-code symphony --workspace /path/to/project
```

<div align="center">
  <img src="../demo.png" alt="Symphony coding agent TUI" height="360">
</div>

## 2. Run a prompt you can verify

Ask for something that must touch the workspace:

```text
Create hello.txt with hi, then read it back.
```

Success looks like: the model streams a reply, a `write_file` / `read_file` row
appears, an approval prompt may ask before overwrite, and `hello.txt` exists on
disk.

## 3. Try the interface

- Type `/` to open the slash-command menu.
- `/model` lists the generated catalog for providers that have credentials.
- `Tab` toggles **build** vs **plan**. Plan mode writes `.symphony/plans/…_plan.md`.
- Type `@` after whitespace to insert a workspace path.
- `Esc` or `Ctrl+X` cancels the in-flight run.

## 4. Resume a session

```sh
uv run --package symphony-code symphony --resume
```

Sessions live in `<workspace>/.symphony/sessions.sqlite3`. If resume lists the
conversation you just had, persistence is working.

## 5. Same loop, as a library

```python
from core_ai import build_default_registry, default_model_id
from coding_agent import CodingAgent

registry = build_default_registry()
agent = CodingAgent(
    registry=registry,
    model_id=default_model_id(registry),
    workspace=".",
)
result = await agent.run("Create hello.txt with hi, then read it back.")
print(result.output_text)
```

The harness itself has no coding-agent assumptions. Wrap any Python callable:

```python
from core_ai import build_default_registry, default_model_id
from core_harness import CoreHarness, Tool

def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

registry = build_default_registry()
harness = CoreHarness(
    registry=registry,
    model_id=default_model_id(registry),
    system_prompt="You are a concise coding assistant.",
    tools=[Tool(read_file)],
)
result = await harness.run("Inspect README.md and summarize it.")
print(result.output_text)
```

**What to read next:** daily use is the [TUI](../user-guide/tui.md). Building
your own agent is [symphony-harness](../packages/symphony-harness.md). How the
pieces fit is [Architecture](../developer-guide/architecture.md).
