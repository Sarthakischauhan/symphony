# symphony-code

Run an AI coding agent in your terminal, or import the coding-agent API from the Symphony workspace. Package import name: `coding_agent`.

**Availability:** version 0.0.3 is on PyPI. Version 0.0.4, including session artifacts and security updates, is being prepared.

```sh
python -m pip install symphony-code
symphony --workspace /path/to/project
```

To run the current `main` branch instead of the published release, clone the repository, run `uv sync`, then `uv run --package symphony-code symphony --workspace /path/to/project`.

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

### Browser interface

Run `symphony web --workspace /path/to/project` to launch Symphony Web. Installed
wheels include the React frontend; Node.js is not needed by end users. See the
[Web guide](../docs/developer-guide/web.md) for development and security details.
