## coding_agent

Coding agent product on top of `core_harness`.

### Surface

- `CodingAgent` — wires workspace tools into `CoreHarness`
- tools (one module each): `read_file`, `write_file`, `bash`, `grep`
- `build_tools(workspace)` — register all tools for a workspace root

```python
from core_ai import ModelRegistry, OpenAIProvider
from coding_agent import CodingAgent

registry = ModelRegistry()
registry.register("openai", OpenAIProvider(api_key=...))

agent = CodingAgent(
    registry=registry,
    model_id="openai:gpt-4o-mini",
    workspace="./.workspace",
)

result = await agent.run("Create hello.txt with hi, then read it back.")
print(result.output_text)
```

### Tool pattern

Each tool lives in its own file under `coding_agent/tools/`:

1. Subclass `WorkspaceTool`
2. Set `name` and `description`
3. Implement `run(...)` with typed parameters
4. Register the class in `TOOL_CLASSES` inside `tools/__init__.py`

Shared path safety and `as_harness_tool()` live in `tools/base.py`.

### Layout

- `agent.py` — `CodingAgent`
- `tools/base.py` — `WorkspaceTool`
- `tools/read_file.py` — `ReadFileTool`
- `tools/write_file.py` — `WriteFileTool`
- `tools/bash.py` — `BashTool`
- `tools/grep.py` — `GrepTool`
- `prompts.py` — default system prompt
