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
  SearchHit,
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
  result?: string;
  started_at?: number;
  duration_ms?: number;
  exit_code?: number | null;
  summary?: ToolSummary | null;
  search_results?: SearchHit[] | null;
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
const startedAt = (value: number | undefined) =>
  typeof value === "number" ? new Date(value * 1000).toISOString() : undefined;

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
  countOrNull(value.removed) &&
  countOrNull(value.start_line);
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
  const value = p.result;
  const failed = p.status !== undefined && p.status !== "success";
  const rendered = failed
    ? value
    : widgetOutput(tool, value, p.search_results, p.summary?.start_line ?? null);
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
// The latest top-level `context` event: tokens in the window and its size.
export type ContextGauge = { used: number; limit: number | null };
// The latest top-level `usage` event. A key is set only when the payload has it.
export type UsageBreakdown = { input?: number; output?: number; reasoning?: number };
export type State = {
  rows: Row[];
  pending: Record<string, InputRequestedFrame>;
  busy: boolean;
  error: string;
  model: string;
  context: ContextGauge | null;
  usage: UsageBreakdown | null;
};
export const initial = (): State => ({
  rows: [],
  pending: {},
  busy: false,
  error: "",
  model: "",
  context: null,
  usage: null,
});
const count = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
export function contextOf(payload: Record<string, unknown>): ContextGauge | null {
  const used = count(payload.tokens_used);
  if (used === undefined) return null;
  const limit = count(payload.context_limit);
  return { used, limit: limit ? limit : null };
}
export function usageOf(payload: Record<string, unknown>): UsageBreakdown {
  const out: UsageBreakdown = {};
  const input = count(payload.prompt_tokens),
    output = count(payload.completion_tokens),
    reasoning = count(payload.reasoning_tokens);
  if (input !== undefined) out.input = input;
  if (output !== undefined) out.output = output;
  if (reasoning !== undefined) out.reasoning = reasoning;
  return out;
}
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
  // A question blocks its own call: an approval is settled by the call's
  // tool_execution_started (or the completed event of a denied call), an
  // ask_user question by its call's completion. Other calls, including a
  // subagent's, leave it open; `done` clears whatever is left.
  if (
    frame.event === "tool_execution_started" ||
    frame.event === "tool_execution_completed"
  )
    s.pending = settleQuestions(s.pending, frame.payload.tool_call_id);
  // The header gauge follows the parent agent only; subagents have their own window.
  if (frame.event === "context" && !frame.payload.parent_id)
    s.context = contextOf(frame.payload);
  if (frame.event === "usage" && !frame.payload.parent_id)
    s.usage = usageOf(frame.payload);
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

// Persisted tool_calls carry their arguments as the JSON of an object.
const parseInput = (raw: string): ToolArguments => {
  const value: unknown = JSON.parse(raw);
  return isRecord(value) ? value : {};
};
// Pending questions that are not waiting on `toolCallId`.
function settleQuestions(
  pending: State["pending"],
  toolCallId: string,
): State["pending"] {
  const open = Object.entries(pending).filter(
    ([, q]) => q.metadata?.tool_call_id !== toolCallId,
  );
  return open.length === Object.keys(pending).length
    ? pending
    : Object.fromEntries(open);
}

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
        toolName: call.function.name,
        input: toolInput(parseInput(call.function.arguments)),
        state: "input-available",
      };
      row.parts.push(tool);
      tools.set(call.id, tool);
    }
    s.rows.push(row);
  }
  for (const [i, [event, payload]] of data.events.entries()) {
    if (event === "context" && !payload.parent_id) s.context = contextOf(payload);
    if (event === "usage" && !payload.parent_id) s.usage = usageOf(payload);
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

// Shape a successful result for the SDK widget. Search renders the
// protocol's search_results (else the plain text); patch keeps its status
// sentence as `message` so the before/after inputs supply the diff; read_file
// passes its code as `content` with its start_line; ask_user passes the
// answer explicitly.
function widgetOutput(
  tool: AgentToolPart,
  value: unknown,
  hits?: SearchHit[] | null,
  startLine: number | null = null,
) {
  if (tool.toolName === "search" && hits)
    return { results: hits, total: hits.length };
  if (tool.toolName === "patch" && typeof value === "string")
    return { message: value };
  if (tool.toolName === "read_file" && typeof value === "string")
    return readFileOutput(value, startLine);
  if (tool.toolName === "ask_user" && typeof value === "string")
    return { answer: value };
  return value;
}
// read_file numbers every line (`numbered_text`): the line's number,
// right-aligned to one width of at least 4, then `|`. The model pages with
// those numbers, so the result keeps them; the widget draws its own gutter.
// The tool records the first number per call as `summary.start_line`, so the
// prefix of every line is known in advance: walk the lines, drop each exact
// prefix, and stop at the first line without its own (the final newline or the
// truncation note). With no start_line (an image read, an old session) the
// text passes through as is.
type ReadFileOutput = { content: string; startLine?: number };
function readFileOutput(text: string, startLine: number | null): ReadFileOutput {
  if (startLine === null) return { content: text };
  const lines = text.split("\n");
  const prefix = (index: number, width: number) =>
    `${String(startLine + index).padStart(width)}|`;
  // The width is that of the last number, which is at most the line count
  // past start_line; exactly one candidate fits the first line.
  const widest = Math.max(4, String(startLine + lines.length - 1).length);
  let width = Math.max(4, String(startLine).length);
  while (width <= widest && !lines[0].startsWith(prefix(0, width))) width += 1;
  if (width > widest) return { content: text };
  const code: string[] = [];
  for (const line of lines) {
    const own = prefix(code.length, width);
    if (!line.startsWith(own)) break;
    code.push(line.slice(own.length));
  }
  return { content: code.join("\n"), startLine };
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
