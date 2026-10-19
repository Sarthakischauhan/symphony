// Translate Symphony stdio frames and journals into @sarchauhan/chat messages.
// Backend-specific mappings stay outside the published, backend-neutral SDK.
import {
  normalizeAgentParts,
  type AgentDataPart,
  type AgentPart,
  type AgentToolPart,
} from "@sarchauhan/protocol";
import type {
  EventFrame,
  Frame,
  InputRequestedFrame,
  SessionHistory,
  ToolArguments,
  ToolSummary,
} from "./frames";

export type Row = {
  id: string;
  role: "user" | "assistant";
  parts: AgentPart[];
};
export type SubagentData = {
  id: string;
  title: string;
  task?: string;
  state: "running" | "completed" | "failed";
  messages: Row[];
  // The spawn_agent call (protocol 3 parent_call_id) and the latest turn.
  label?: string;
  callId?: string;
  step?: number;
};
// Protocol 3 completion fields, live or from the session journal.
export type ToolFacts = {
  status?: string;
  result?: unknown;
  output?: unknown;
  content?: unknown;
  started_at?: number | string;
  duration_ms?: number;
  exit_code?: number | null;
  summary?: ToolSummary | null;
};
export type TerminalChunk = { stream: "stdout" | "stderr"; text: string };
// Facts the chat SDK reads off a tool's output object. Absent fields stay unset
// so an older session does not invent an exit code or a duration.
type RunMeta = {
  summary?: ToolSummary;
  startedAt?: string;
  durationMs?: number;
  exitCode?: number;
  chunks?: TerminalChunk[];
};
const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
// The harness stamps started_at as epoch seconds (a float) on the wire.
const startedAt = (value: number | string | undefined) =>
  typeof value === "number"
    ? new Date(value * 1000).toISOString()
    : typeof value === "string"
      ? value
      : undefined;

function runMeta(p: ToolFacts, chunks?: TerminalChunk[]): RunMeta {
  const meta: RunMeta = {};
  if (p.summary) meta.summary = p.summary;
  const started = startedAt(p.started_at);
  if (started) meta.startedAt = started;
  if (typeof p.duration_ms === "number") meta.durationMs = p.duration_ms;
  if (typeof p.exit_code === "number") meta.exitCode = p.exit_code;
  if (chunks?.length) meta.chunks = chunks;
  return meta;
}
const countOrNull = (value: unknown): value is number | null =>
  value === null || typeof value === "number";
export const isToolSummary = (value: unknown): value is ToolSummary =>
  isRecord(value) &&
  countOrNull(value.lines) &&
  countOrNull(value.matches) &&
  countOrNull(value.added) &&
  countOrNull(value.removed);
export const isTerminalChunk = (value: unknown): value is TerminalChunk =>
  isRecord(value) &&
  (value.stream === "stdout" || value.stream === "stderr") &&
  typeof value.text === "string";
const terminalChunks = (value: unknown): TerminalChunk[] | undefined =>
  Array.isArray(value) ? value.filter(isTerminalChunk) : undefined;
const metaOf = (output: unknown): RunMeta =>
  isRecord(output)
    ? {
        summary: isToolSummary(output.summary) ? output.summary : undefined,
        startedAt: typeof output.startedAt === "string" ? output.startedAt : undefined,
        durationMs: typeof output.durationMs === "number" ? output.durationMs : undefined,
        exitCode: typeof output.exitCode === "number" ? output.exitCode : undefined,
        chunks: terminalChunks(output.chunks),
      }
    : {};

// Settle a tool card from its completion payload.
function finish(tool: AgentToolPart, p: ToolFacts) {
  const value = p.output ?? p.result ?? p.content;
  const failed = p.status !== undefined && p.status !== "success";
  const rendered = failed ? value : widgetOutput(tool, value);
  const meta = { ...metaOf(tool.output), ...runMeta(p) };
  tool.state = failed ? "output-error" : "output-available";
  tool.output = withMeta(rendered, meta);
  // Bash renders through the terminal widget, which already shows the result
  // and the exit code. Other tools have no body for a failed call, so the
  // result stays in errorText.
  if (failed && typeof value === "string" && tool.toolName !== "bash")
    tool.errorText = value;
}
const subagentTitle = (data: SubagentData) =>
  data.step ? `${data.label || "Subagent"} · step ${data.step}` : data.label || "Subagent";
export type UsageData = { total_tokens: number };
export type ContextData = { current_tokens: number; context_window: number };
export type State = {
  rows: Row[];
  pending: Record<string, InputRequestedFrame>;
  busy: boolean;
  error: string;
  model: string;
};
export const initial = (): State => ({
  rows: [],
  pending: {},
  busy: false,
  error: "",
  model: "",
});
// Copy-on-write editing. A frame shallow-copies only the state, rows and
// parts it changes, so unchanged rows keep their identity (MessageRow is
// memoized) and a frame costs O(changed parts), not a transcript deep clone.
type Draft = WeakSet<object>;
function own<T extends object>(d: Draft, value: T): T {
  if (d.has(value)) return value;
  const copy = (Array.isArray(value) ? [...value] : { ...value }) as T;
  d.add(copy);
  return copy;
}
// Edit a row of an already-owned rows array.
function editRow(d: Draft, rows: Row[], index: number): Row {
  const row = own(d, rows[index]);
  row.parts = own(d, row.parts);
  rows[index] = row;
  return row;
}
// Edit a part of an already-edited row.
function editPart<T extends AgentPart>(d: Draft, row: Row, index: number): T {
  const part = own(d, row.parts[index]) as T;
  row.parts[index] = part;
  return part;
}
// Newest match first: live frames almost always target the last row.
function locate(
  rows: Row[],
  test: (part: AgentPart) => boolean,
): [number, number] | undefined {
  for (let r = rows.length - 1; r >= 0; r--) {
    const p = rows[r].parts.findLastIndex(test);
    if (p >= 0) return [r, p];
  }
}
// Mark streaming text and reasoning done, copying the row only if needed.
function settle(d: Draft, rows: Row[], index: number) {
  const parts = rows[index]?.parts;
  if (!parts?.some((part) => streams(part) && part.state !== "done")) return;
  const row = editRow(d, rows, index);
  parts.forEach((part, i) => {
    if (streams(part) && part.state !== "done")
      editPart<typeof part>(d, row, i).state = "done";
  });
}
const streams = (part: AgentPart) =>
  part.type === "reasoning" || part.type === "text";
type SubagentCard = AgentDataPart & { data: SubagentData };
const isSubagent = (part: AgentPart): part is SubagentCard =>
  part.type === "data" && part.name === "subagent";
// The matching subagent card, copied with its own data for editing.
function editSubagent(
  d: Draft,
  rows: Row[],
  test: (data: SubagentData) => boolean,
): SubagentCard | undefined {
  const at = locate(rows, (part) => isSubagent(part) && test(part.data));
  if (!at) return;
  const card = editPart<SubagentCard>(d, editRow(d, rows, at[0]), at[1]);
  card.data = own(d, card.data);
  return card;
}
const isTool = (part: AgentPart): part is AgentToolPart => part.type === "tool";
// Replace a usage/context data part with the latest event payload; the SDK
// renders it below the message.
function show(
  d: Draft,
  row: Row,
  name: "usage" | "context",
  data: UsageData | ContextData,
) {
  const index = row.parts.findIndex(
    (x) => x.type === "data" && x.name === name,
  );
  if (index >= 0) editPart<AgentDataPart>(d, row, index).data = data;
  else row.parts.push({ type: "data", name, data });
}
const toolInput = (args: ToolArguments) => ({
  ...args,
  before: args.old_str,
  after: args.new_str,
});

export function reduce(state: State, frame: Frame, id: number): State {
  const d: Draft = new WeakSet();
  const s = own(d, state);
  switch (frame.type) {
    case "ready":
      if (frame.model) s.model = frame.model;
      return s;
    case "input_requested":
      s.pending = { ...s.pending, [frame.request_id]: frame };
      return s;
    case "done":
      s.rows = own(d, s.rows);
      settle(d, s.rows, s.rows.length - 1);
      s.busy = false;
      s.pending = {};
      return s;
    case "error":
      s.error = frame.message;
      return s;
    case "event":
      return applyEvent(d, s, frame, id);
  }
}

// `s` is owned by this frame; everything reachable from it is shared until
// copied with own/editRow/editPart.
function applyEvent(d: Draft, s: State, frame: EventFrame, id: number): State {
  s.rows = own(d, s.rows);
  if (frame.event === "subagent_step") {
    const card = editSubagent(
      d,
      s.rows,
      (data) => data.id === frame.payload.agent_id,
    );
    if (card) {
      card.data.step = frame.payload.turn;
      card.data.title = subagentTitle(card.data);
    }
    return s;
  }
  if (frame.event === "tool_execution_output") {
    // Chunks carry no agent ids; parent_call_id names the spawning call.
    const call = frame.payload.parent_call_id;
    if (call) {
      const card = editSubagent(d, s.rows, (data) => data.callId === call);
      if (card)
        card.data.messages = applyEvent(
          d,
          { ...initial(), rows: card.data.messages },
          { ...frame, payload: { ...frame.payload, parent_call_id: null } },
          id,
        ).rows;
      return s;
    }
    const at = locate(
      s.rows,
      (x) => isTool(x) && x.toolCallId === frame.payload.tool_call_id,
    );
    const found = at && s.rows[at[0]].parts[at[1]];
    if (found && isTool(found) && found.state === "input-available") {
      const tool = editPart<AgentToolPart>(d, editRow(d, s.rows, at[0]), at[1]);
      const prior = metaOf(tool.output);
      const stream = frame.payload.stream === "stderr" ? "stderr" : "stdout";
      const chunks = [...(prior.chunks ?? [])];
      const last = chunks.at(-1);
      // The terminal widget joins chunk text, so consecutive deltas on one
      // stream merge; long outputs stay a few chunks instead of thousands.
      if (last?.stream === stream)
        chunks[chunks.length - 1] = {
          stream,
          text: last.text + frame.payload.delta,
        };
      else chunks.push({ stream, text: frame.payload.delta });
      tool.output = withMeta(undefined, { ...prior, chunks });
    }
    return s;
  }
  // A question blocks the run, so any later event means it was answered.
  if (frame.event !== "question_asked") s.pending = {};
  if (frame.payload.parent_id) {
    const card = editSubagent(
      d,
      s.rows,
      (data) => data.id === frame.payload.agent_id,
    );
    if (card) {
      const child = applyEvent(
        d,
        { ...initial(), rows: card.data.messages },
        {
          ...frame,
          payload: { ...frame.payload, parent_id: undefined },
        } as EventFrame,
        id,
      );
      card.data.messages = child.rows;
    }
    return s;
  }
  // The protocol's run_started event carries the prompt for this turn.
  if (frame.event === "run_started") {
    settle(d, s.rows, s.rows.length - 1);
    s.busy = true;
    if (frame.payload.prompt)
      s.rows.push({
        id: `u-${id}`,
        role: "user",
        parts: [{ type: "text", text: frame.payload.prompt }],
      });
    return s;
  }
  if (frame.event === "question_asked") return s;
  if (s.rows.at(-1)?.role !== "assistant")
    s.rows.push({ id: `a-${id}`, role: "assistant", parts: [] });
  const index = s.rows.length - 1;
  const row = editRow(d, s.rows, index);
  const last = row.parts.length - 1;
  switch (frame.event) {
    case "reasoning_delta": {
      const part = row.parts[last];
      if (part?.type === "reasoning" && part.state === "streaming")
        editPart<typeof part>(d, row, last).text += frame.payload.delta;
      else
        row.parts.push({
          type: "reasoning",
          text: frame.payload.delta,
          state: "streaming",
        });
      break;
    }
    case "reasoning_completed":
      settle(d, s.rows, index);
      break;
    case "text_delta": {
      const part = row.parts[last];
      if (part?.type === "text")
        editPart<typeof part>(d, row, last).text += frame.payload.delta;
      else {
        settle(d, s.rows, index);
        row.parts.push({
          type: "text",
          text: frame.payload.delta,
          state: "streaming",
        });
      }
      break;
    }
    case "usage":
      show(d, row, "usage", { total_tokens: frame.payload.cumulative_tokens });
      break;
    case "context":
      if (frame.payload.context_limit)
        show(d, row, "context", {
          current_tokens: frame.payload.tokens_used,
          context_window: frame.payload.context_limit,
        });
      break;
    case "tool_execution_started":
    case "tool_execution_updated":
    case "tool_execution_completed": {
      const p = frame.payload;
      settle(d, s.rows, index);
      const at = row.parts.findIndex(
        (x) => isTool(x) && x.toolCallId === p.tool_call_id,
      );
      let tool: AgentToolPart;
      if (at >= 0) tool = editPart<AgentToolPart>(d, row, at);
      else {
        tool = {
          type: "tool",
          toolCallId: p.tool_call_id,
          toolName: p.tool_name || "tool",
          state: "input-available",
        };
        row.parts.push(tool);
      }
      if (p.arguments) tool.input = toolInput(p.arguments);
      if (frame.event === "tool_execution_started") {
        const prior = metaOf(tool.output);
        tool.output = withMeta(undefined, runMeta(p, prior.chunks));
      }
      if (frame.event === "tool_execution_completed") finish(tool, p);
      break;
    }
    case "agent_spawned":
    case "agent_completed":
    case "agent_failed": {
      const p = frame.payload;
      const key = String(p.child_id);
      let card = editSubagent(d, s.rows, (data) => data.id === key);
      if (!card) {
        card = {
          type: "data",
          name: "subagent",
          id: key,
          data: {
            id: key,
            title: p.label || "Subagent",
            label: p.label,
            state: "running",
            messages: [],
          },
        };
        row.parts.push(card);
      }
      const data = card.data;
      data.task = p.prompt || data.task;
      data.callId = p.parent_call_id || p.tool_call_id || data.callId;
      data.state =
        frame.event === "agent_spawned"
          ? "running"
          : frame.event === "agent_completed"
            ? "completed"
            : "failed";
      if (!data.messages.length && p.output_text)
        data.messages = [
          {
            id: key,
            role: "assistant",
            parts: [{ type: "text", text: p.output_text }],
          },
        ];
      break;
    }
  }
  return s;
}

const parseInput = (raw: ToolArguments | string | undefined): ToolArguments => {
  if (typeof raw !== "string") return raw || {};
  try {
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object"
      ? (value as ToolArguments)
      : { raw };
  } catch {
    return { raw };
  }
};

export function historical(data: SessionHistory): State {
  const s = initial(),
    tools = new Map<string, AgentToolPart>();
  for (const [index, m] of data.messages.entries()) {
    if (m.role === "system") continue;
    if (m.role === "tool") {
      const t = m.tool_call_id ? tools.get(m.tool_call_id) : undefined;
      if (t) {
        t.output = widgetOutput(t, m.content);
        t.state = "output-available";
      }
      continue;
    }
    const parts: AgentPart[] =
      typeof m.content === "string"
        ? [{ type: "text", text: m.content }]
        : normalizeAgentParts(
            (m.content || []).flatMap((part) =>
              typeof part.type === "string"
                ? [{ ...part, type: part.type }]
                : [],
            ),
          );
    const row: Row = { id: `h-${index}`, role: m.role, parts };
    for (const call of m.tool_calls || []) {
      const tool: AgentToolPart = {
        type: "tool",
        toolCallId: call.id,
        toolName: call.function?.name || call.name || "tool",
        input: toolInput(
          parseInput(call.function?.arguments ?? call.arguments),
        ),
        state: "input-available",
      };
      row.parts.push(tool);
      tools.set(call.id, tool);
    }
    s.rows.push(row);
  }
  for (const [i, [event, payload]] of data.events.entries()) {
    // Protocol 3 journals duration_ms, exit_code and summary with each call.
    if (event === "tool_execution_completed" && !payload.parent_id) {
      const tool = tools.get(String(payload.tool_call_id));
      if (tool) finish(tool, payload as ToolFacts);
    }
    if (
      event === "agent_spawned" ||
      event === "agent_completed" ||
      event === "agent_failed" ||
      event === "subagent_step"
    )
      Object.assign(
        s,
        reduce(s, { type: "event", event, payload } as EventFrame, -i - 1),
      );
  }
  return s;
}

// Symphony's search tool answers "N content matches" then "path:line:text"
// lines (or bare paths in files mode); the SDK search view wants results.
function searchResults(value: string) {
  const [summary, ...lines] = value.split("\n");
  if (!/^\d+ (content|files) matches/.test(summary)) return value;
  return {
    total: Number.parseInt(summary, 10),
    results: lines.filter(Boolean).map((line) => {
      const match = /^(.+?):(\d+):(.*)$/.exec(line);
      return match
        ? { path: match[1], line: Number(match[2]), text: match[3] }
        : { path: line };
    }),
  };
}
// The SDK treats a plain patch result string as a candidate unified diff.
// Symphony returns a status sentence; retain it as metadata so before/after
// inputs can supply the actual diff instead of falling back to a generic tool.
function widgetOutput(tool: AgentToolPart, value: unknown) {
  if (tool.toolName === "search" && typeof value === "string")
    return searchResults(value);
  const input = tool.input as { before?: unknown; after?: unknown } | undefined;
  if (
    tool.toolName === "patch" &&
    typeof value === "string" &&
    typeof input?.before === "string" &&
    typeof input?.after === "string" &&
    !/^(@@|diff --git|--- |\*\*\* Begin Patch)/m.test(value)
  )
    return { message: value };
  return value;
}
// Keep protocol 3 facts beside the rendered result. A string result (bash,
// read) moves under `output` so it is not mistaken for a diff or a summary.
function withMeta(value: unknown, meta: RunMeta) {
  const present = Object.values(meta).some((item) => item !== undefined);
  if (!present) return value;
  const base = isRecord(value)
    ? value
    : value === undefined
      ? {}
      : { output: value };
  return { ...base, ...meta };
}
