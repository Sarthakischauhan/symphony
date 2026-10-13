# symphony-code

Run an AI coding agent in your terminal, or import the coding-agent API from the Symphony workspace. Package import name: `coding_agent`.

**Availability:** this package is not currently published on PyPI. To run it today, use a checkout of the repository:

```sh
git clone https://github.com/Sarthakischauhan/symphony.git
cd symphony
uv sync
uv run --package symphony-code symphony --workspace /path/to/project
```

`symphony`, `symphony-code`, and `coding-agent-tui` are aliases for the same terminal application. Configure a provider on first launch, or set credentials beforehand. See the [installation guide](../docs/getting-started/installation.md) and [quickstart](../docs/getting-started/quickstart.md).

## Use the library

From the repository workspace:

```python
from core_ai import build_default_registry, default_model_id
from coding_agent import CodingAgent

registry = build_default_registry()
agent = CodingAgent(
    registry=registry,
    model_id=default_model_id(registry),
    workspace=".")
result = await agent.run("Fix the failing test")
print(result.output_text)
```

## Next steps

- [Terminal UI and controls](../docs/user-guide/tui.md)
- [Configuration and approvals](../docs/user-guide/configuration.md)
- [Tools and workspace access](../docs/user-guide/tools.md)
- [Sessions and resume](../docs/user-guide/sessions.md)
- [Package API guide](../docs/packages/symphony-code.md)

**Safety:** tools run with the current user's permissions; approval prompts do not sandbox commands or restrict paths. Read the [security policy](../SECURITY.md) before use.