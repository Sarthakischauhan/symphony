# config/

Example and template files that are not shipped inside a package. Copy them
where the loader looks; the files here are never read at runtime.

| File | Copy to |
| --- | --- |
| `coding_agent/config.example.json` | `~/.symphony/config.json` (shape reference; spawn writes a full file on first run) |
| `coding_agent/dashboard.toml.example` | `<workspace>/.symphony/dashboard.toml` or `<workspace>/dashboard.toml` |

Defaults that ship with a package live in that package's own `config/`
folder, for example `coding_agent/src/coding_agent/config/personalities.json`.
