# Skills and local plugins

Skills provide reusable instructions to Symphony Code. Plugins can package skills and, optionally, trusted Python add-ons. This guide describes the coding agent's current local loading behavior; it does not imply marketplace or remote installation support.

## Skills

A skill is a directory containing `SKILL.md`. Bundled skills ship with the coding agent; user skills can be placed under `~/.symphony/skills/<name>/`. A skill may include bounded metadata such as a name, description, and declared arguments. The agent can read the instructions and referenced resources when relevant. Discovery does not execute scripts.

## Local plugins and trust

Plugin configuration lives in `~/.symphony/config.json`. A plugin directory can contain a `plugin.json` manifest, skills, and an optional add-on factory. Resource-only plugins do not import Python. Python add-on code is imported only when the plugin is explicitly enabled and its resolved directory is beneath a configured `authorized_roots` entry.

**Authorized add-on code runs with the same operating-system permissions as Symphony.** Only authorize code you trust. Plugin authorization is not a sandbox; see [Security](../../SECURITY.md).

The loader supports local directories only. It does not download plugins, resolve dependencies, or provide a marketplace. Changes take effect when a new agent is created; there is no hot unload for an already-running agent.

## Configure a plugin

A minimal shape is:

```json
{
  "plugins": {
    "enabled": true,
    "authorized_roots": ["/absolute/path/to/trusted-plugins"],
    "entries": [
      {"path": "/absolute/path/to/trusted-plugins/example", "enabled": true}
    ]
  }
}
```

Relative paths resolve from the project root; authorized roots must be configured intentionally. The `/installed` TUI command shows discovered skills and plugins. To disable a plugin, turn off its entry or remove it from configuration, then start a new agent.

See the [add-on guide](./extending.md) for the harness hook API and the [configuration guide](../user-guide/configuration.md) for user-facing setup.
