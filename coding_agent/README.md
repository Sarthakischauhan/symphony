## coding_agent

Minimal coding agent product on top of `core_harness`.

### Surface

- `CodingAgent` — wires workspace tools into `CoreHarness`
- tools: `read`, `write`, `bash` (scoped to a workspace directory)

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

### Layout

- `agent.py` — `CodingAgent`
- `tools.py` — workspace-scoped read / write / bash
- `prompts.py` — default system prompt
