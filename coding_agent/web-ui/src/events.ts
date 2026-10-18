export type Row = { id: string; role: string; parts: any[] };
export type State = {
  rows: Row[];
  pending: Record<string, any>;
  busy: boolean;
  error: string;
};
export const initial = (): State => ({
  rows: [],
  pending: {},
  busy: false,
  error: "",
});
// Backend-specific mappings stay outside the published, backend-neutral SDK.
export function reduce(state: State, frame: any, id: number): State {
  const s = structuredClone(state),
    p = frame.payload || {};
  if (frame.type === "user") {
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
    s.busy = false;
    s.pending = {};
  }
  if (frame.type === "error") s.error = frame.message;
  if (frame.type !== "event") return s;
  if (p.parent_id) {
    const card = s.rows
      .flatMap((r) => r.parts)
      .find((x) => x.type === "web-subagent" && x.subagent.id === p.agent_id);
    if (card) {
      const payload = { ...p };
      delete payload.parent_id;
      const child = reduce(
        { ...initial(), rows: card.subagent.messages || [] },
        { ...frame, payload },
        id,
      );
      card.subagent.messages = child.rows;
    }
    return s;
  }
  if (frame.event === "run_started") s.busy = true;
  let row = s.rows.at(-1);
  if (!row || row.role !== "assistant") {
    row = { id: `a-${id}`, role: "assistant", parts: [] };
    s.rows.push(row);
  }
  if (frame.event === "text_delta") {
    const last = row.parts.at(-1);
    if (last?.type === "text") last.text += p.delta;
    else row.parts.push({ type: "text", text: p.delta });
  }
  if (frame.event?.startsWith("tool_execution_")) {
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
      output: p.output ?? p.result ?? p.content,
      state: frame.event.endsWith("started")
        ? "input-available"
        : p.status === "error"
          ? "output-error"
          : "output-available",
    });
  }
  if (frame.event === "tool_execution_completed" && p.status === "success") {
    const tool = row.parts.find(
      (x) => x.type === "tool" && x.toolCallId === p.tool_call_id,
    );
    if (tool?.toolName === "write_file")
      row.parts.push({
        type: "web-artifact",
        artifact: {
          id: p.tool_call_id,
          filename: tool.input.path,
          mediaType: "text/plain",
          status: "ready",
          content: tool.input.content,
        },
      });
  }
  if (
    ["agent_spawned", "agent_completed", "agent_failed"].includes(frame.event)
  ) {
    const key = String(p.child_id);
    let card = s.rows
      .flatMap((r) => r.parts)
      .find((x) => x.type === "web-subagent" && x.subagent.id === key);
    if (!card) {
      card = {
        type: "web-subagent",
        subagent: { id: key, title: p.label || "Subagent" },
      };
      row.parts.push(card);
    }
    Object.assign(card.subagent, {
      task: p.prompt || card.subagent.task,
      state:
        frame.event === "agent_spawned"
          ? "running"
          : frame.event === "agent_completed"
            ? "completed"
            : "failed",
      messages: card.subagent.messages?.length
        ? card.subagent.messages
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
      if (t) Object.assign(t, { output: m.content, state: "output-available" });
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
