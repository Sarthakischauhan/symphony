// Symphony stdio protocol frames as the web host relays them over SSE.
// Request replies (sessions, session_history, models, commands,
// model_selected) are answered over HTTP and never reach this stream.

export type ReadyFrame = {
  type: "ready";
  session_id: string;
  model: string;
  workspace: string;
  branch: string;
  client: string;
  protocol_version: number;
  capabilities: string[];
};
export type InputRequestedFrame = {
  type: "input_requested";
  request_id: string;
  question: string;
  choices: string[] | null;
  default?: string | null;
  kind?: string | null;
  metadata?: Record<string, unknown>;
  // Protocol 3 approvals: what is touched, the question, the write size.
  target?: string;
  detail?: string;
  bytes?: number | null;
};
export type DoneFrame = {
  type: "done";
  status: "completed" | "interrupted" | "errored" | "worker_exited";
};
export type ErrorFrame = {
  type: "error";
  message: string;
  request_id?: string;
};

// Subagent events carry their parent and agent ids on any payload.
type Routed = { parent_id?: string; agent_id?: string };
export type ToolArguments = Record<string, unknown> & {
  old_str?: string;
  new_str?: string;
};
// Protocol 3 tool summary counts; null where a tool has no such count.
export type ToolSummary = {
  lines: number | null;
  matches: number | null;
  added: number | null;
  removed: number | null;
  // Patch only: the 1-based file line where old_str matched.
  start_line: number | null;
};
// One search tool result (protocol 3 `search_results`); files mode has no line.
export type SearchHit = { path: string; line: number | null; text: string };
// The spawn_agent call a subagent's event belongs to (protocol 3).
type Spawned = { parent_call_id?: string | null };
// tool_execution_started carries arguments and started_at (epoch seconds);
// tool_execution_completed carries status, result and the protocol 3 facts.
type ToolPayload = Routed & Spawned & {
  tool_call_id: string;
  call_id?: string;
  started_at?: number;
  duration_ms?: number;
  exit_code?: number | null;
  summary?: ToolSummary | null;
  search_results?: SearchHit[] | null;
  tool_name?: string;
  arguments?: ToolArguments;
  status?: "success" | "error" | "cancelled" | "timeout";
  result?: string;
};
type AgentPayload = Routed & Spawned & {
  child_id: string;
  tool_call_id?: string;
  label?: string;
  prompt?: string;
  output_text?: string;
};
export type StdioEvent =
  | {
      event: "run_started";
      payload: Routed & { prompt?: string; model_id?: string };
    }
  | { event: "text_delta"; payload: Routed & { delta: string } }
  | { event: "reasoning_delta"; payload: Routed & { delta: string } }
  | { event: "reasoning_completed"; payload: Routed }
  | {
      event: "usage";
      payload: Routed & {
        cumulative_tokens: number;
        estimated?: boolean;
        // Per model call; reasoning_tokens is absent from estimated usage.
        prompt_tokens?: number;
        completion_tokens?: number;
        reasoning_tokens?: number;
        total_tokens?: number;
      };
    }
  | {
      event: "context";
      payload: Routed & { tokens_used: number; context_limit: number | null };
    }
  | {
      event: "tool_execution_started" | "tool_execution_completed";
      payload: ToolPayload;
    }
  | {
      event: "tool_execution_output";
      payload: Spawned & {
        tool_call_id: string;
        delta: string;
        stream?: "stdout" | "stderr";
      };
    }
  | {
      event: "subagent_step";
      payload: Routed & Spawned & { turn?: number; started_at?: number };
    }
  | {
      event: "agent_spawned" | "agent_completed" | "agent_failed";
      payload: AgentPayload;
    }
  | { event: "question_asked"; payload: Routed & { request_id: string } };
export type EventFrame = { type: "event" } & StdioEvent;
export type Frame =
  ReadyFrame | InputRequestedFrame | DoneFrame | ErrorFrame | EventFrame;

const FRAME_TYPES = new Set([
  "ready",
  "input_requested",
  "done",
  "error",
  "event",
]);
const isObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
// Events this client does not render (e.g. run_completed) are dropped.
const EVENTS = new Set<string>([
  "run_started",
  "text_delta",
  "reasoning_delta",
  "reasoning_completed",
  "usage",
  "context",
  "tool_execution_started",
  "tool_execution_completed",
  "tool_execution_output",
  "subagent_step",
  "agent_spawned",
  "agent_completed",
  "agent_failed",
  "question_asked",
]);

/** Narrow one decoded SSE payload to a frame this client renders. */
export function parseFrame(value: unknown): Frame | null {
  if (!isObject(value) || typeof value.type !== "string") return null;
  if (!FRAME_TYPES.has(value.type)) return null;
  if (value.type === "event")
    return typeof value.event === "string" &&
      EVENTS.has(value.event) &&
      isObject(value.payload)
      ? (value as EventFrame)
      : null;
  return value as Frame;
}

// Replies to the web host's typed requests.
export type SessionSummary = {
  session_id: string;
  updated_at: string;
  message_count: number;
  first_message: string;
  client: string;
  active: boolean;
};
// A persisted assistant tool call; `arguments` is a JSON string.
export type ToolCall = {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
};
export type HistoryMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string | Record<string, unknown>[] | null;
  tool_call_id?: string;
  tool_calls?: ToolCall[] | null;
};
export type JournalEvent = [string, Record<string, unknown>];
export type SessionHistory = {
  messages: HistoryMessage[];
  events: JournalEvent[];
  children: Record<string, unknown>[];
};
export type SlashCommand = {
  name: string;
  description: string;
  inputHint: string | null;
  options: { value: string; label: string; description: string }[];
};
// /api/info: the workspace and branch from the worker's ready frame.
export type Workspace = {
  path: string;
  display: string;
  name: string;
  branch: string;
};
