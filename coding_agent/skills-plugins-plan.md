# Skills and plugins for coding_agent

Status: implementation proposal. Nothing in this document is shipped behavior.

## Task for Symphony

Implement local skill discovery and local plugin loading in `coding_agent`,
using the existing `Addon` and `Tool` APIs. Follow the phases and acceptance
criteria below. Inspect the current tree before editing; names below are proposed
APIs, not claims that those APIs exist. Preserve existing behavior when no skills
or plugins are configured. Do not implement the separate control-plane redesign.

Read `AGENTS.md`, `SECURITY.md`, `plan.md`, `coding_agent/agent.py`, the product
configuration, workspace tool base, and harness addon lifecycle first. Paths
for Python modules in this document are relative to their package's `src/`.

## Ownership and scope

| Concept | Meaning | Location |
| --- | --- | --- |
| Skill | Markdown instructions with optional reference files and scripts | Product-managed resource directories |
| Tool | Model-callable operation with validated arguments | `coding_agent/tools/` or an enabled plugin |
| Addon | Installs tools/services and receives lifecycle hooks | Existing harness interface; product implementation |
| Plugin | Manifest describing a collection of skills and an optional addon factory | Local plugin directory |

`core_harness` remains unaware of plugin manifests, discovery directories,
filesystem trust, and skill syntax. `CodingAgent` resolves product resources and
passes ordinary addon instances to `CoreHarness`. The TUI consumes events and
shows diagnostics through its existing mechanisms.

Build these components:

- `SkillRegistry`: metadata discovery and canonical skill resource roots.
- `SkillsAddon`: supplies the catalog and explicit read-only resource roots to
  product composition; it does not register new model-facing tools.
- `PluginManager`: validates configured packages and constructs their addons
  before harness construction. This is a product loader, not another runtime.
- An optional plugin's addon uses the existing `Addon.attach()` and hooks.
  Do not introduce a container addon that secretly delegates every lifecycle hook.

First release supports local directories only. Exclude marketplaces, downloads,
package installation, dependency resolution, hot reload, MCP integration, and
new web-search functionality. A documentation-only example plugin is sufficient.

## Resource formats

### Skills

Discover immediate child directories containing `SKILL.md` under:

- `~/.symphony/skills/`
- `<workspace>/.symphony/skills/`
- Skill directories listed by enabled plugin manifests.

A skill uses YAML front matter with required `name` and `description`:

```markdown
---
name: research
description: Find authoritative sources and produce cited findings.
---

Search with the available web_search tool. Read relevant sources before
making claims. Include source links in the answer.
```

Use safe YAML parsing and a strict metadata model. Add a direct dependency if
needed; never rely on an incidental transitive dependency. Validate bounded name,
description, and file sizes. Do not silently truncate executable instructions:
reject oversized skill documents with a clear diagnostic.

Optional resources may live under `references/`, `scripts/`, or `assets/`.
Discovery reads metadata only and never imports or executes resource files.
Reject symlinks that resolve outside the discovered skill directory.

Use stable qualified identifiers:

- `user/research`
- `workspace/research`
- `plugin/<plugin-id>/research`

Use qualified IDs for catalog identity and diagnostics, not tool arguments.
Display the origin, description, and absolute `SKILL.md` path; tool calls use paths.
Reject duplicate IDs; do not silently shadow skills. Sort catalogs deterministically.
Validate names as single identifier segments without slashes or traversal syntax.

### Plugins

Support explicitly configured local paths and this versioned manifest:

```json
{
  "schema_version": 1,
  "id": "web-research",
  "version": "0.1.0",
  "description": "Research instructions and optional search tools",
  "skills": ["skills/research"],
  "addon": {
    "file": "addon.py",
    "factory": "create_addon"
  }
}
```

`addon` is optional, allowing resource-only plugins. Resolve every listed path
relative to the plugin root; reject absolute paths and escapes, including symlink
escapes. Reject unsupported schema versions, duplicate IDs, malformed manifests,
and invalid factory names before importing code. Version is informational in v1;
do not imply dependency compatibility solving.

Proposed factory contract:

```python
def create_addon(context: PluginContext) -> Addon:
    ...
```

`PluginContext` contains the resolved workspace, plugin root, and validated
plugin-specific configuration. It does not expose the TUI app object. Plugins
that need current interaction can use the same explicit tool/control-plane
interfaces available today. Do not create a new interaction API for this task.

Load a package under a unique module namespace so different plugins can use the
same filenames and relative imports. Import only after enablement checks. A
resource-only plugin must never trigger Python imports from its directory.

## Configuration and trust

Add strict skill and plugin configuration models to `CodingAgentConfig`, with
backward-compatible defaults. Skills may default to discovery enabled; executable
plugins default to disabled. Respect explicit disable flags. Missing conventional
skill directories are normal and should not create warnings.

Workspace plugin entries describe the path, whether requested enabled, and
plugin configuration. Workspace configuration alone must not authorize new
Python code: the repository and agent can write that file.

Use a separate user-controlled authorization source under `~/.symphony/` or an
explicit host API parameter for trusted plugin roots. Do not write that trust
source automatically during discovery. Define trust as authorization for code at
that canonical local root, including later edits; show this scope in setup docs.
Changes to an authorized root are the user's responsibility in this initial local
version. Do not claim content pinning or code isolation.

A plugin with Python code loads only when both requested enabled and authorized.
A missing authorization produces an actionable diagnostic without importing it.
No installation-time scripts, subprocesses, or network calls are needed by the
loader. Executable addons run with application privileges; their `attach()` and
hooks are trusted host code, not actions mediated by tool approval.

Skill text grants no authority. Its scripts never run automatically. Requested
shell execution uses the existing `bash` tool and current approval behavior.
Do not add a shell shortcut. Extend only `read_file` with explicit skill resource
roots as described below; keep writes and other workspace tools confined to their
existing path boundaries.

Before implementing executable plugin loading, discuss the concrete trust-source
and enablement behavior as required by `AGENTS.md`. Update `SECURITY.md` when it
ships. Skill discovery and reading can be implemented independently first.

## Read skills through the existing tool

Reuse `read_file` for `SKILL.md` and its references. Do not add `load_skill`,
`read_skill_resource`, a plugin-reading tool, or skill activation state. The
application reads plugin manifests and loads addons; the model reads skill files.

Extend the product `ReadFileTool` constructor with explicit read-only resource
roots supplied from validated skill discovery. These are host configuration,
never model-controlled tool arguments. Preserve existing workspace-relative
paths; permit absolute paths only when they resolve inside the workspace or an
explicitly supplied skill root. Catalog entries give the exact absolute path to
`SKILL.md`; instructions explain how to resolve relative references against its
containing directory before calling `read_file`.

Allow only individual discovered skill directories, not the whole user home,
`.symphony` directory, or plugin package. A plugin's skill directory grants no
read access to sibling code, configuration, or credentials outside that root.
Recheck canonical containment on every read, including symlink resolution and
path traversal. External skill reads use the existing output bounds, pagination,
content handling, and error conventions of `read_file`.

Keep this exception local to the read tool. Do not broaden
`WorkspaceTool.resolve_path()` for write, patch, search, or other tools. Ordinary
workspace reads retain current behavior. Test that an external allowed skill can
be read while adjacent files and escaping symlinks remain inaccessible, and that
write/patch still reject those same external paths.

Reading script source never executes it. Shell execution remains governed by
existing approval policy and is not filesystem-isolated. Repeated reads work
normally after compaction; there is no permanent "already loaded" flag.

This read-only exception is an intentional extension of the current workspace
read boundary, agreed in the planning discussion. Implement that specific scope
and update `SECURITY.md` and tool docs when it ships; do not turn it into general
filesystem access or an additional approval prompt for each skill read.

## Catalog and run integration

At startup, discover skills and enabled plugins, collect plugin skill roots,
create addon instances, and construct the harness. Avoid recursive registration
from `attach()`: resolve plugin addons before `CoreHarness` construction, then
pass a normal flat addon list.

`SkillsAddon` supplies catalog metadata and resource roots through an explicit
product integration path. Configure the existing `ReadFileTool` with those roots
before use; do not replace it or register a duplicate. Product prompt assembly
in `CodingAgent.run()` includes one deterministic catalog section containing ID,
description, absolute `SKILL.md` path, and instructions to use `read_file`. Do not append catalog
messages on every `before_turn`; do not duplicate the catalog across runs.

Keep skill bodies in tool results rather than permanently inserting them into
the system prompt. The catalog remains available after compaction so the model
can reload needed instructions. Resume uses the same configured discovery roots;
missing previously used skills produce explicit errors when requested.

Bound discovery count and catalog size through configuration. If the configured
catalog exceeds the limit, report which resources cannot be exposed; never hide
truncation. Avoid semantic ranking or model-based selection in v1.

Preserve these existing composition details:

- `CodingAgent` rewrites its system prompt on each run; integrate the catalog
  there or through an explicit product helper that survives that rewrite.
- Plan mode keeps its existing `read_file` and `search` tool list. Skill files
  use the configured read tool; no extra tools are needed. Never expose arbitrary
  plugin tools in plan mode by default.
- An explicit `tools=` list remains authoritative. Do not add plugin tools,
  replace custom read implementations, or broaden their access implicitly.
  Require explicit opt-in to configure skill roots for host-supplied tools; omit
  catalog entries whose files the supplied tools cannot read.
- Child setup currently uses `addon_factory`, so a `fork_for_child()` method
  alone will not integrate skills. Wire the product's child factory deliberately.
- Children may share immutable skill metadata but get their own addon/tool
  instances. Executable plugin addons are not inherited automatically. Respect
  deliberate child configuration without enabling nested spawning or changing
  current child approval defaults.

Audit tool registration collisions. The harness currently overwrites duplicate
tool names. Reject plugin attempts to replace built-in tools or other plugin
tools, preferably through generic duplicate registration validation if compatible
with existing callers. Test any harness adjustment and keep plugin-specific
logic out of `core_harness`. Reject duplicate addon names as well.

For explicitly enabled malformed plugins or factory/attach failures, fail agent
construction with plugin attribution rather than leave a partially configured
agent usable. For malformed standalone skills, omit the bad skill and report a
bounded diagnostic while allowing valid skills to load. Trusted plugin code may
have side effects that cannot be rolled back; do not promise transactional imports.

## Suggested files

```text
coding_agent/src/coding_agent/
  skills/
    __init__.py
    models.py
    registry.py
    addon.py
  plugins/
    __init__.py
    models.py
    manager.py
  tools/
    read_file.py                # Extend existing tool with read-only skill roots
  config.py                     # Product settings integration
  agent.py                      # Discovery, prompt, addon, and child assembly

coding_agent/tests/
  test_skills.py
  test_plugins.py
  test_skill_agent_integration.py

docs/developer-guide/
  skills-and-plugins.md          # Create when implementation ships
```

Use temporary skill/plugin fixtures in tests. Follow existing test layout if it
has changed. Keep the existing learning, compaction, and persistence behavior.

## Implementation phases and acceptance criteria

### Phase 1: Skill resources

Implement metadata models, discovery, and the registry of canonical skill roots.

Acceptance: user and workspace skills have stable IDs; malformed YAML and
oversized files produce useful diagnostics; missing roots are harmless; duplicate
IDs and escaping paths cannot silently resolve to another resource. Discovery
never executes Python or scripts.

### Phase 2: SkillsAddon and agent integration

Extend the existing `read_file` with explicit read-only skill roots; implement
catalog composition and explicit child integration using current harness APIs.

Acceptance: a mocked model sees the catalog, calls `read_file` on the listed
`SKILL.md`, reads a reference with the same tool, and finishes a run. Cover both
workspace and external skill roots. Adjacent external files and escaping symlinks
are rejected; external writes and patches remain rejected. Repeated runs do not
duplicate the catalog. Compaction does not prevent rereading. Restricted `tools=`
callers and plan mode retain their tool lists. There are no dedicated skill tools
or activation state. No approval-policy or control-plane refactor is introduced.

### Phase 3: Local plugin packaging

Implement manifest validation, explicit path configuration, resource-only plugins,
and then authorized Python addon factories after the trust behavior is discussed.

Acceptance: a resource-only plugin contributes skills without executing code;
an unauthorized code plugin is never imported; an authorized fixture registers a
working tool. Unknown schema versions, duplicate plugin/addon/tool names, escaping
paths, missing factories, and factory failures produce deterministic diagnostics.
Two plugins with the same module filenames do not collide. Children do not gain
plugin capabilities accidentally.

### Phase 4: Product feedback and documentation

Expose loader diagnostics through existing TUI notices and to headless callers.
Normal `read_file` events display skill file reads, alongside plugin tool calls;
avoid bespoke events unless a real UI requirement needs them. If new harness
events are necessary, update `ControlPlaneEventType` and both event documents.

Write setup, authoring, configuration, trust, limitations, and removal instructions.
Include one resource-only example and one small executable example requiring no
API credentials. Removing a configured plugin affects the next agent construction;
hot unloading an active run is out of scope.

Acceptance: users can configure a local skill or plugin from the documentation,
understand why an entry is disabled, and remove it without editing harness code.
Update package-facing docs consistently, `SECURITY.md` for shipped guarantees,
and the completed/open status in `plan.md`.

## Validation and completion

Use mocked providers and local temporary fixtures only. Never require provider
keys, network access, or real user home-directory writes in tests. Inject the
user resource/trust roots for tests. Add regression tests for existing composition
and tool filtering, not just tests that mirror parser implementation.

Run targeted tests for each phase, then `uv run pytest` and
`uv run ruff check .`. Run the documented package build check for the integrated
change where appropriate. Report changes, test results, and remaining limitations.

The work is complete when skills can be discovered and loaded on demand, enabled
local plugins contribute ordinary addons and skills, existing runs still work
without configuration, and the docs accurately describe the implemented trust
and lifecycle behavior. Do not stop at scaffolding or a manifest parser.
