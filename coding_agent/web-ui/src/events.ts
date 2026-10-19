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
  duration_ms?: number;
  exit_code?: number | null;
  summary?: ToolSummary | null;
};

/** "bash · exit 1 · 2.3s · 4 lines"; undefined when the payload has no facts. */
export function toolTitle(name: string, p: ToolFacts): string | undefined {
  const facts: string[] = [];
  if (typeof p.exit_code === "number" && p.exit_code !== 0)
    facts.push(`exit ${p.exit_code}`);
  if (typeof p.duration_ms === "number")
    facts.push(`${(p.duration_ms / 1000).toFixed(1)}s`);
  const s = p.summary;
  if (s?.added != null)
    facts.push(s.removed != null ? `+${s.added} −${s.removed}` : `+${s.added}`);
  else if (s?.matches != null) facts.push(`${s.matches} matches`);
  else if (s?.lines != null) facts.push(`${s.lines} lines`);
  return facts.length ? [name, ...facts].join(" · ") : undefined;
}

// Settle a tool card from its completion payload.
function finish(tool: AgentToolPart, p: ToolFacts) {
  const value = p.output ?? p.result ?? p.content;
  const failed = p.status !== undefined && p.status !== "success";
  tool.state = failed ? "output-error" : "output-available";
  tool.output = failed ? value : widgetOutput(tool, value);
  if (failed && typeof value === "string") tool.errorText = value;
  tool.title = toolTitle(tool.toolName, p) ?? tool.title;
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
const settle = (row: Row | undefined) =>
  row?.parts.forEach((part) => {
    if (part.type === "reasoning" || part.type === "text") part.state = "done";
  });
const isSubagent = (
  part: AgentPart,
): part is AgentDataPart & { data: SubagentData } =>
  part.type === "data" && part.name === "subagent";
const subagents = (rows: Row[]) =>
  rows.flatMap((r) => r.parts).filter(isSubagent);
const isTool = (part: AgentPart): part is AgentToolPart => part.type === "tool";
// Replace a usage/context data part with the latest event payload; the SDK
// renders it below the message.
function show(
  row: Row,
  name: "usage" | "context",
  data: UsageData | ContextData,
) {
  const part = row.parts.find((x) => x.type === "data" && x.name === name);
  if (part?.type === "data") part.data = data;
  else row.parts.push({ type: "data", name, data });
}
const toolInput = (args: ToolArguments) => ({
  ...args,
  before: args.old_str,
  after: args.new_str,
});

export function reduce(state: State, frame: Frame, id: number): State {
  const s = structuredClone(state);
  switch (frame.type) {
    case "ready":
      if (frame.model) s.model = frame.model;
      return s;
    case "input_requested":
      s.pending[frame.request_id] = frame;
      return s;
    case "done":
      settle(s.rows.at(-1));
      s.busy = false;
      s.pending = {};
      return s;
    case "error":
      s.error = frame.message;
      return s;
    case "event":
      return applyEvent(s, frame, id);
  }
}

function applyEvent(s: State, frame: EventFrame, id: number): State {
  if (frame.event === "subagent_step") {
    const card = subagents(s.rows).find(
      (x) => x.data.id === frame.payload.agent_id,
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
      const card = subagents(s.rows).find((x) => x.data.callId === call);
      if (card)
        card.data.messages = applyEvent(
          { ...initial(), rows: card.data.messages },
          { ...frame, payload: { ...frame.payload, parent_call_id: null } },
          id,
        ).rows;
      return s;
    }
    const tool = s.rows
      .flatMap((r) => r.parts)
      .filter(isTool)
      .find((x) => x.toolCallId === frame.payload.tool_call_id);
    if (tool && tool.state === "input-available")
      tool.output = `${typeof tool.output === "string" ? tool.output : ""}${frame.payload.delta}`;
    return s;
  }
  // A question blocks the run, so any later event means it was answered.
  if (frame.event !== "question_asked") s.pending = {};
  if (frame.payload.parent_id) {
    const card = subagents(s.rows).find(
      (x) => x.data.id === frame.payload.agent_id,
    );
    if (card) {
      const child = applyEvent(
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
    settle(s.rows.at(-1));
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
  let row = s.rows.at(-1);
  if (!row || row.role !== "assistant") {
    row = { id: `a-${id}`, role: "assistant", parts: [] };
    s.rows.push(row);
  }
  switch (frame.event) {
    case "reasoning_delta": {
      const last = row.parts.at(-1);
      if (last?.type === "reasoning" && last.state === "streaming")
        last.text += frame.payload.delta;
      else
        row.parts.push({
          type: "reasoning",
          text: frame.payload.delta,
          state: "streaming",
        });
      break;
    }
    case "reasoning_completed":
      settle(row);
      break;
    case "text_delta": {
      const last = row.parts.at(-1);
      if (last?.type === "text") last.text += frame.payload.delta;
      else {
        settle(row);
        row.parts.push({
          type: "text",
          text: frame.payload.delta,
          state: "streaming",
        });
      }
      break;
    }
    case "usage":
      show(row, "usage", { total_tokens: frame.payload.cumulative_tokens });
      break;
    case "context":
      if (frame.payload.context_limit)
        show(row, "context", {
          current_tokens: frame.payload.tokens_used,
          context_window: frame.payload.context_limit,
        });
      break;
    case "tool_execution_started":
    case "tool_execution_updated":
    case "tool_execution_completed": {
      const p = frame.payload;
      settle(row);
      let tool = row.parts
        .filter(isTool)
        .find((x) => x.toolCallId === p.tool_call_id);
      if (!tool) {
        tool = {
          type: "tool",
          toolCallId: p.tool_call_id,
          toolName: p.tool_name || "tool",
          state: "input-available",
        };
        row.parts.push(tool);
      }
      if (p.arguments) tool.input = toolInput(p.arguments);
      if (frame.event === "tool_execution_started") tool.output = undefined;
      if (frame.event === "tool_execution_completed") finish(tool, p);
      break;
    }
    case "agent_spawned":
    case "agent_completed":
    case "agent_failed": {
      const p = frame.payload;
      const key = String(p.child_id);
      let card = subagents(s.rows).find((x) => x.data.id === key);
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
