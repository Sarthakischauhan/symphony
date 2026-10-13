# Trace runs with Langfuse

Langfuse is an optional integration for inspecting coding-agent runs: model turns, tool calls, and compaction. Traces may contain project code, prompts, and tool output. Enable it only when those data are appropriate to send to the Langfuse project you configured.

## Enable tracing

In the TUI, run `/langfuse` and enter your project keys and endpoint. Alternatively, set these variables in the process environment or an appropriate `.env` file:

```sh
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

When running from a repository checkout without the TUI install flow, install the optional workspace dependency with:

```sh
uv sync --package symphony-code --extra langfuse
```

Without credentials or the optional SDK, tracing stays inactive. Environment variables and storage locations are documented in the [environment reference](../reference/environment.md#langfuse-optional).

## Data handling

The integration redacts trace payloads and replaces image content with placeholders. Redaction is not a guarantee that all sensitive information is removed. Set the configured payload limit and sampling rate appropriately, and review your Langfuse retention and access controls.

For implementation details and the `LangfuseAddon` API, see the package source. The harness extension surface is described in [Extending the harness](../developer-guide/extending.md).
