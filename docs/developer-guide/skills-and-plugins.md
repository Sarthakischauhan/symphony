# Skills and local plugins

`coding_agent` discovers Markdown skills from the package's bundled skills,
`~/.symphony/skills/<name>/`, and `<workspace>/.symphony/skills/<name>/`. Each
directory must contain a bounded `SKILL.md`. YAML front matter loads three
fields: `name`, `description`, and optional `args`. The agent shows that
contract in its prompt and reads the document or resources with `read_file`
when needed. Discovery does not execute scripts.

```markdown
---
name: systematic-debug
description: Reproduce a failure before editing.
args:
  - name: repro
    type: string
    required: true
    description: Command, test, or symptom that fails.
---
```

`args` entries are `name`, `type` (`string`, `number`, `boolean`, or `enum`),
`description`, and optional `required`, `default`, and `enum`. Plugin manifests
load the same `description` and `args` fields from `plugin.json` without
importing addon code.

## Configuration

Plugins are local directories configured in `~/.symphony/config.json`. Relative
plugin paths resolve from the project root; absolute paths can point to
user-wide plugins such as `~/.symphony/plugins/<name>`:

```json
{
  "plugins": {
    "enabled": true,
    "authorized_roots": ["/absolute/path/to/trusted-plugins"],
    "entries": [{"path": "/absolute/path/to/research-plugin", "enabled": true}]
  }
}
```

A plugin contains `plugin.json` with `schema_version: 1`, an `id`, optional
relative `skills` directories, and optionally an `addon` (`file` and factory
name). Resource-only plugins never import Python. Addon code is imported only
when the plugin is enabled and its resolved directory is below an explicitly
configured `authorized_roots` entry. Treat authorized plugin code as trusted:
it runs with the same user permissions as the agent.

Malformed manifests, duplicate IDs or addon names, path escapes, and failed
factories are reported as loader diagnostics. Plugin paths and skill roots are
bounded; workspace write and patch tools remain workspace-scoped.

## Removal and lifecycle

To remove an extension, delete its plugin/skill entry from `.symphony/config.json`
or set a plugin's `enabled` value to `false`, then construct the next agent.
There is no hot unload: an already-running agent keeps its loaded addons until
that run ends. The `/installed` command opens a read-only inventory of discovered
skills and configured plugins. No special removal tool is exposed to the model.

The loader supports local directories only; it does not download packages,
resolve dependencies, use marketplaces, or integrate MCP.
