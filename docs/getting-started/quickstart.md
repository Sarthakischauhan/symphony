# Quickstart

Get one clean conversation working before you change config, spawn subagents,
or wire the HTTP server.

## 1. Launch and add a provider

```sh
uv run --package symphony-code symphony
```

If no API key is set, Symphony asks which provider to use (OpenAI, Anthropic,
Gemini, or Grok), then for that provider's key. Keys are saved to
`~/.symphony/.env`. Add another provider from the same screen, or later with
`/provider`.

You can still export a key yourself before launch:

```sh
export OPENAI_API_KEY=sk-...
uv run --package symphony-code symphony
```

The default workspace is the current directory. Point it somewhere else with
`--workspace`:

```sh
uv run --package symphony-code symphony --workspace /path/to/project
```

<video src="../demo.mp4" controls muted loop playsinline poster="../demo.png" width="800">
  <a href="../demo.mp4">Demo: create hello.py, write a test, run pytest — 1 passed</a>
</video>

## 2. Run a prompt you can verify

Ask for something that must touch the workspace:

```text
Create hello.py with a greet() function and a test, then run it.
```

Success looks like the demo above: Write / Bash rows in the transcript, then
`hello.py` and `test_hello.py` on disk, and pytest reporting **1 passed**. An
approval prompt may ask before overwrite or bash.

## 3. Try the interface

- Type `/` to open the slash-command menu.
- `/provider` adds another OpenAI, Anthropic, Gemini, or Grok key without restarting.
- `/model` lists the generated catalog for providers that have credentials.
- `Tab` toggles **build** vs **plan**. Plan mode writes `.symphony/plans/…_plan.md`.
- Type `@` after whitespace to insert a workspace path.
- `Esc` or `Ctrl+X` cancels the in-flight run.

## 4. Resume a session

```sh
uv run --package symphony-code symphony --resume
```

Sessions live in `<workspace>/.symphony/sessions/`. If resume lists the
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
result = await agent.run("Create hello.py with a greet() function and a test, then run it.")
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
