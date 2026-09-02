# TUI

The TUI is a conversation surface over the harness event stream. It does not
scrape stdout. Every tool row, token, usage line, and compaction notice is a
control-plane event.

On first launch with no credentials, a provider screen asks which API to use
and for a key. That key is saved to `<workspace>/.env`. Add more providers
later with `/provider`; `/model` then lists every credentialed catalog.

```sh
uv run --package symphony-code symphony
uv run --package symphony-code symphony --workspace /path/to/project
uv run --package symphony-code symphony --model gemini:gemini-3.7-flash
```


<div align="center">
  <img src="../demo.png" alt="Symphony TUI" height="340">
</div>

## Keybindings

| Keys | Action |
| --- | --- |
| `Esc` / `Ctrl+X` | Cancel the in-flight run |
| `Ctrl+L` or `/clear` | Reset the visible transcript |
| `Ctrl+D`, `/quit`, `/exit` | Leave the TUI |
| `Tab` | Toggle build ↔ plan without opening the menu |
| `/` | Slash-command palette |
| `@` | Workspace file search (after whitespace) |

## Build vs plan

**Build** can read, edit, and run. **Plan** is read-only: it inspects the repo
and writes a streamed plan to a task-named file such as
`.symphony/plans/to_build_a_server_plan.md`. Plan mode uses a yellow composer
border. When planning finishes, a modal offers **Build now**. `/plan` opens a
searchable picker of saved workspace plans.

## Composer extras

- `@` after whitespace opens the same selector as model/command pickers. Tab
  or Enter inserts `@path` without sending.
- Drop an image onto the composer (terminals paste the file path) to attach a
  clickable `[Image 1]` chip.
- `generate_image` writes the asset to disk and uses the same chip on the tool
  row.

<div align="center">
  <img src="../image-support.png" alt="Image chips in the TUI" height="220">
</div>

## Approvals

The control plane owns approval, not wrapped tools. Default `approvals.mode`
is `ask`. Choose **Allow once**, **Deny**, or **Always allow**. Always-allow
is a **run-level** override — it applies to the current run and its children,
and does not rewrite `.symphony/config.json`.

## Subagent sessions

Click a Subagent row to open a nested session with the same transcript chrome.
Children run without approval prompts; the parent approval mode is unchanged.

<div align="center">
  <img src="../subagent-spawn.gif" alt="Nested subagent session" height="280">
</div>

The full command list is on [Slash commands](../reference/slash-commands.md).
