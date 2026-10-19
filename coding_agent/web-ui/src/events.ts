// Translate Symphony stdio frames and journals into @sarchauhan/chat messages.
// Backend-specific mappings stay outside the published, backend-neutral SDK.
export type Row = { id: string; role: string; parts: any[] };
export type State = {
  rows: Row[];
  pending: Record<string, any>;
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
const dataPart = (row: Row, name: string, id?: string) =>
  row.parts.find((x) => x.type === "data" && x.name === name && x.id === id);
// Upsert a usage/context data part; the SDK renders it below the message.
function meter(row: Row, name: string, update: (data: any) => void) {
  let part = dataPart(row, name);
  if (!part) {
    part = { type: "data", name, data: {} };
    row.parts.push(part);
  }
  update(part.data);
}
const subagents = (rows: Row[]) =>
  rows
    .flatMap((r) => r.parts)
    .filter((x) => x.type === "data" && x.name === "subagent");

export function reduce(state: State, frame: any, id: number): State {
  const s = structuredClone(state),
    p = frame.payload || {};
  if (frame.type === "ready" && frame.model) s.model = frame.model;
  if (frame.type === "user") {
    settle(s.rows.at(-1));
    s.rows.push({
      id: `u-${id}`,
      role: "user",
      parts: [{ type: "text", text: frame.text }],
    });
    s.busy = true;
  }
  if (frame.type === "input_requested") s.pending[frame.request_id] = frame;
  if (frame.type === "answered") delete s.pending[frame.request_id];
  if (frame.type === "done") {
    settle(s.rows.at(-1));
    s.busy = false;
    s.pending = {};
  }
  if (frame.type === "error") s.error = frame.message;
  if (frame.type !== "event") return s;
  if (p.parent_id) {
    const card = subagents(s.rows).find((x) => x.data.id === p.agent_id);
    if (card) {
      const payload = { ...p };
      delete payload.parent_id;
      const child = reduce(
        { ...initial(), rows: card.data.messages || [] },
        { ...frame, payload },
        id,
      );
      card.data.messages = child.rows;
    }
    return s;
  }
  if (frame.event === "run_started") s.busy = true;
  let row = s.rows.at(-1);
  if (!row || row.role !== "assistant") {
    row = { id: `a-${id}`, role: "assistant", parts: [] };
    s.rows.push(row);
  }
  if (frame.event === "reasoning_delta" && p.delta) {
    const last = row.parts.at(-1);
    if (last?.type === "reasoning" && last.state === "streaming")
      last.text += p.delta;
    else
      row.parts.push({ type: "reasoning", text: p.delta, state: "streaming" });
  }
  if (frame.event === "reasoning_completed") settle(row);
  if (frame.event === "text_delta") {
    const last = row.parts.at(-1);
    if (last?.type === "text") last.text += p.delta;
    else {
      settle(row);
      row.parts.push({ type: "text", text: p.delta, state: "streaming" });
    }
  }
  if (frame.event === "usage")
    meter(row, "usage", (data) => {
      data.input_tokens = (data.input_tokens || 0) + (p.prompt_tokens || 0);
      data.output_tokens =
        (data.output_tokens || 0) + (p.completion_tokens || 0);
      if (p.reasoning_tokens)
        data.reasoning_tokens =
          (data.reasoning_tokens || 0) + p.reasoning_tokens;
      data.total_tokens = p.cumulative_tokens;
    });
  if (frame.event === "context" && p.context_limit)
    meter(row, "context", (data) => {
      data.current_tokens = p.tokens_used || 0;
      data.context_window = p.context_limit;
    });
  if (frame.event?.startsWith("tool_execution_")) {
    settle(row);
    let tool = row.parts.find(
      (x) => x.type === "tool" && x.toolCallId === p.tool_call_id,
    );
    if (!tool) {
      tool = {
        type: "tool",
        toolCallId: p.tool_call_id,
        toolName: p.tool_name,
      };
      row.parts.push(tool);
    }
    Object.assign(tool, {
      input: p.arguments
        ? {
            ...p.arguments,
            before: p.arguments.old_str,
            after: p.arguments.new_str,
          }
        : tool.input,
      output:
        p.status === "success"
          ? widgetOutput(tool, p.output ?? p.result ?? p.content)
          : (p.output ?? p.result ?? p.content),
      state: frame.event.endsWith("started")
        ? "input-available"
        : p.status === "error"
          ? "output-error"
          : "output-available",
    });
  }
  // A written file renders as the SDK artifact card through its tool output.
  if (frame.event === "tool_execution_completed" && p.status === "success") {
    const tool = row.parts.find(
      (x) => x.type === "tool" && x.toolCallId === p.tool_call_id,
    );
    if (tool?.toolName === "write_file")
      tool.output = {
        artifact: {
          id: p.tool_call_id,
          filename: tool.input.path,
          mediaType: "text/plain",
          status: "ready",
          content: tool.input.content,
        },
      };
  }
  if (
    ["agent_spawned", "agent_completed", "agent_failed"].includes(frame.event)
  ) {
    const key = String(p.child_id);
    let card = subagents(s.rows).find((x) => x.data.id === key);
    if (!card) {
      card = {
        type: "data",
        name: "subagent",
        id: key,
        data: { id: key, title: p.label || "Subagent" },
      };
      row.parts.push(card);
    }
    Object.assign(card.data, {
      task: p.prompt || card.data.task,
      state:
        frame.event === "agent_spawned"
          ? "running"
          : frame.event === "agent_completed"
            ? "completed"
            : "failed",
      messages: card.data.messages?.length
        ? card.data.messages
        : p.output_text
          ? [
              {
                id: key,
                role: "assistant",
                parts: [{ type: "text", text: p.output_text }],
              },
            ]
          : [],
    });
  }
  return s;
}

export function historical(data: any): State {
  const s = initial(),
    tools = new Map<string, any>();
  for (const [index, m] of data.messages.entries()) {
    if (m.role === "system") continue;
    if (m.role === "tool") {
      const t = tools.get(m.tool_call_id);
      if (t)
        Object.assign(t, {
          output: widgetOutput(t, m.content),
          state: "output-available",
        });
      continue;
    }
    const row: Row = {
      id: `h-${index}`,
      role: m.role,
      parts:
        typeof m.content === "string"
          ? [{ type: "text", text: m.content }]
          : m.content || [],
    };
    for (const call of m.tool_calls || []) {
      let input = call.function?.arguments || call.arguments || {};
      if (typeof input === "string") {
        try {
          input = JSON.parse(input);
        } catch {
          input = { raw: input };
        }
      }
      const tool = {
        type: "tool",
        toolCallId: call.id,
        toolName: call.function?.name || call.name,
        input: { ...input, before: input.old_str, after: input.new_str },
        state: "input-available",
      };
      row.parts.push(tool);
      tools.set(call.id, tool);
    }
    s.rows.push(row);
  }
  for (const [i, [event, payload]] of (data.events || []).entries()) {
    if (["agent_spawned", "agent_completed", "agent_failed"].includes(event))
      Object.assign(s, reduce(s, { type: "event", event, payload }, -i - 1));
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
function widgetOutput(tool: any, value: any) {
  if (tool.toolName === "search" && typeof value === "string")
    return searchResults(value);
  if (
    tool.toolName === "patch" &&
    typeof value === "string" &&
    typeof tool.input?.before === "string" &&
    typeof tool.input?.after === "string" &&
    !/^(@@|diff --git|--- |\*\*\* Begin Patch)/m.test(value)
  )
    return { message: value };
  return value;
}
