# Coding agent host protocols

`stdio.py` is the versioned JSONL boundary for desktop and other external
hosts. The coding agent owns execution and persisted checkpoints. A host owns
its composer queue and submits a single prompt per active turn.

The `ready` frame carries `session_id`, `model`, `workspace`, `branch`,
`client`, `protocol_version` (currently `4`) and `capabilities`. Protocol 2
advertised `runs`, `resume`, `interrupt`, `input`, `steer`, `models`, `images`,
`subagents`, and `commands`; protocol 3 adds `sessions`, `model_switch` and
`widget_fields`; protocol 4 adds `artifacts`. A host sends `run`, `answer`, `interrupt`, or `steer`
commands, or a request with a `request_id` (below), and reads `event`,
`input_requested`, `error`, `done`, and reply frames. `answer`, `interrupt`,
and `steer` are passed to `CoreHarness.submit` as `Answer`, `Interrupt`, and
`UserInput` operations. `{"type":"steer","prompt":"..."}` adds a user message
to the active run before its next model call and is an error when no run is
active.

A question arrives as the ordinary `question_asked` event, the same as in
every other host, followed by the protocol 2 `input_requested` frame with the
same `request_id`. Reply to either with one `answer` command.
Unknown control-plane events can be ignored without losing the terminal
`done` frame. A later version must change the version number when it changes
required frame semantics.

After `ready`, send `{"type":"model/list","request_id":"catalog-1"}` on stdin.
Symphony responds with a `models` frame carrying the same `request_id`. Each
row has a qualified
`id` (`provider:model`), display `label`, `provider`, `description`,
`context_limit` (tokens, or null), and `reasoning_levels`. The default ID is
also returned as `default`; hosts should keep the qualified ID when selecting
a model. The provider is the API route, so gateway models identify the gateway
even when its upstream model has another vendor.

## Requests

Each request carries a `request_id` and gets exactly one reply frame with the
same `request_id`, or an `error` frame with it.

| Request | Reply | Capability |
| --- | --- | --- |
| `{"type":"model/list"}` | `models`: `models` rows and `default` | `models` |
| `{"type":"command/list"}` | `commands`: the slash-command catalog | `commands` |
| `{"type":"session/list"}` | `sessions`: this client's parent sessions, newest first, each with `session_id`, `updated_at`, `message_count`, `first_message`, `client`, `active` | `sessions` |
| `{"type":"session/history","session_id":"..."}` | `session_history`: `session_id`, `messages` (the transcript; assistant `tool_calls` are `{id, type: "function", function: {name, arguments}}` with `arguments` a JSON string), `events` (`[event, payload]` journal pairs) and `children` | `sessions` |
| `{"type":"model","model":"provider:model"}` | `model_selected`: `model`, `context_limit`; an error during an active run | `model_switch` |
| `{"type":"artifacts_list","session_id":"..."}` | `artifacts`: `session_id`, `artifacts` (manifests in creation order); `session_id` defaults to this worker's session | `artifacts` |
| `{"type":"artifacts_get","session_id":"...","artifact_id":"..."}` | `artifact`: `session_id`, `artifact` (the manifest), `path` (absolute path of the entry file), `files` (the latest version's files, relative to its folder) | `artifacts` |

## Subagents

Subagents use the ordinary `event` envelope: the parent emits
`agent_spawned` with `child_id` and `tool_call_id`; child events carry that
`child_id` as `agent_id`; the parent emits `agent_completed` or `agent_failed`
with `child_id` when it settles. Hosts can route child traffic into a nested
view using the spawning tool call ID.

## Protocol 3: widget fields

`ready` reports `"protocol_version": 3` and the `widget_fields` capability. Every
protocol 2 key is unchanged; hosts that ignore unknown keys keep working.
The stdio server and the TUI add these fields through one shared
`coding_agent.widget_fields.EventFields`. `parent_call_id` is the
`tool_call_id` of the `spawn_agent` call that started the emitting subagent,
and `null` for top-level events.

| Event | Added fields |
| --- | --- |
| `tool_execution_started` | `call_id`, `parent_call_id` (`started_at` was already present) |
| `tool_execution_output` | `call_id`, `stream` (`"stdout"` or `"stderr"`), `parent_call_id` (from the call's `tool_execution_started`) |
| `tool_execution_completed` | `call_id`, `exit_code`, `summary`, `search_results`, `parent_call_id` (`status`, `result` and `duration_ms` were already present) |
| `question_asked` (approval) | `target`, `detail`, `bytes` (`tool_call_id`, `choices`, `default` were already present) |
| `question_asked` (`ask_user`) | `tool_call_id`: the asking call |
| `input_requested` (approval) | top-level `target`, `detail`, `bytes` (also kept in `metadata`) |
| `agent_spawned` | `parent_call_id` (same value as `tool_call_id`) |
| `subagent_step` (new, derived) | `session_id` (the parent session), `agent_id`, `parent_id`, `parent_call_id`, `turn`, `started_at`; follows each subagent `turn_started` |

- `exit_code` is the bash process's exit status; it is `null` for other tools,
  background jobs, and timeouts. A non-zero exit is `status: "error"` and the
  result starts with `exit=N`, but consumers should read `exit_code`.
- `summary` is `{lines, matches, added, removed, start_line}`, each an
  integer or `null`: `lines` for bash and read_file, `matches` for search,
  `lines` and `added` for write_file, `added`, `removed` and `start_line` for
  patch, and `start_line` for read_file too. Failed non-bash calls report all
  `null`.
- `start_line` is recorded per call by the tool, never parsed from `result`.
  For patch it is the 1-based line, in the file as it was before the edit,
  where `old_str` first matched. For read_file it is the number of the first
  line of a text read (its `offset`); each result line is that number plus its
  index, right-aligned to one width, then `|`. It is `null` for image reads
  and reads that returned no lines.
- `search_results` (search only, else `null`) lists the search tool's results
  in order: `{path, line, text}`, where `line` is `null` and `text` is empty
  in files mode. `summary.matches` is its length.
- Answer a question or an approval with the `answer` command:
  `{"type":"answer","request_id":"...","value":"<one of choices>"}`.
- `bytes` is the UTF-8 size of a write_file `content` or patch `new_str`, else `null`.
- The session journal stores the same fields: `build_agent` gives the
  JSONL store its own `EventFields`, approval questions are emitted through
  the harness so they are journaled, and `subagent_step` is journaled in the
  parent session. `session/history` events and resumed sessions therefore
  carry `call_id`, `parent_call_id`, `duration_ms`, `exit_code`, `summary`,
  `search_results`,
  the approval `target`/`detail`/`bytes`, and `subagent_step`.
- `tool_execution_output` chunks are live only. Bash emits them on the sink,
  outside `CoreHarness.emit`, so they are not stamped or journaled; the
  completed event's `result` is the stored output. Journaling `stream` per
  chunk needs a core change: route chunks through `CoreHarness.emit` (or hand
  tools a stamped emit).
- Sessions recorded before protocol 3 lack these fields. Clients render those
  calls without the facts; they do not derive them from `result` text.

## Protocol 4: artifacts

`ready` reports `"protocol_version": 4` and the `artifacts` capability. Every
protocol 3 frame is unchanged. Symphony keeps the html, csv, json and image
files a run produces as versioned session artifacts, under
`$SYMPHONY_HOME/sessions/<session_id>/artifacts/` (TUI sessions:
`$SYMPHONY_HOME/tui/sessions/<session_id>/artifacts/`):

```
artifacts/index.json                    {"artifacts": [manifest, ...]}
artifacts/<artifact_id>/manifest.json   the latest version's manifest
artifacts/<artifact_id>/v<N>/...        the files of version N
```

Files are written to a temporary name and renamed, so readers never see a
partial version.

A manifest has:

| Field | Meaning |
| --- | --- |
| `id` | 16 hex characters, derived from `kind` and `source`, so rewriting a file versions one artifact |
| `kind` | `"html"`, `"csv"`, `"json"` or `"image"` |
| `title` | Display name: the `save_artifact` title, else the file or folder name |
| `created_at`, `updated_at` | ISO 8601 UTC times of the first and the latest version |
| `version` | Latest version number, from 1 |
| `tool_call_id` | The call that produced the latest version |
| `source` | The workspace path it came from (relative inside the workspace), or `<tool_call_id>#image-<n>` for an image a tool returned inline |
| `entry` | The file to open, relative to the artifact folder, e.g. `v2/index.html` |
| `mime` | The entry's media type: `text/html`, `text/csv`, `application/json`, or `image/png`, `image/jpeg`, `image/webp`, `image/gif`, `image/svg+xml` |
| `sha256` | The entry file's sha256; for a website folder, the sha256 of its sorted `path\0sha256\n` file list |
| `size` | Bytes in the version (all files of a website) |

Capture (the `artifacts` add-on, after each successful tool call):

- `write_file`, `patch` and `generate_image` writing `.html`, `.csv`,
  `.json`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` or `.svg`. CSV must be
  UTF-8 and JSON must parse. `index.html` in a folder below the workspace
  keeps that whole folder (a website with its assets), and writing any file
  inside that folder versions the site again; any other `.html` is a
  single-file artifact.
- Not auto-captured: `package.json`, `package-lock.json`,
  `npm-shrinkwrap.json`, `tsconfig*.json`, `*.config.json`, lockfiles
  (`*.lock`, `*.lockb`, `*-lock.json`, `*-lock.yaml`, `*.lock.json`), anything
  under `node_modules`, `.git`, `dist` or `build`, and a `patch` to an html or
  json file that git tracks (`git ls-files --error-unmatch` in the file's
  repository) unless it is part of a website folder.
- `save_artifact` with `path`, `kind` (one of the four; anything else is
  rejected) and an optional `title`, for files the agent did not write with
  the tools above, such as a command's output or a website folder.
- An image another tool returns inline (not `read_file`).

Content whose sha256 matches the latest version stores nothing and emits
nothing. Otherwise the parent session's harness emits, in the ordinary
`event` envelope and the journal:

| Event | Payload |
| --- | --- |
| `artifact_created` | the manifest plus `path`, the absolute path of the entry file (`version` is 1) |
| `artifact_updated` | the same, for a new version of an existing artifact |

The event payloads also carry the usual stamped keys (`run_id`,
`session_id`, `seq`, `ts`, `agent_id`, `parent_id`). Artifacts produced by a
subagent are stored in, and emitted by, the parent session.
