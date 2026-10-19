// chat@0.0.1 imports these helpers, but protocol@0.0.1 and @0.0.2
// omit them. Keep this backend-neutral bridge until upstream republishes.
export * from "@sarchauhan/protocol-original";

export type ArtifactStatus = "pending" | "ready" | "error";
export type ArtifactData = {
  id: string;
  filename: string;
  mediaType: string;
  status: ArtifactStatus;
  content?: string;
  url?: string;
};
export type SubagentState =
  "queued" | "running" | "completed" | "failed" | "cancelled";
export type SubagentData = {
  id: string;
  title: string;
  state: SubagentState;
  task?: string;
  messages?: unknown[];
};
export type UsageData = {
  input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
};
export type ContextData = { current_tokens?: number; context_window?: number };
// Envelopes the SDK streams; `type` discriminates the payload.
export type CompatData =
  | { type: "data-artifact"; id: string; data: ArtifactData }
  | { type: "data-subagent"; id: string; data: SubagentData };

type Fields = { [key: string]: unknown };
const record = (v: unknown): v is Fields =>
  !!v && typeof v === "object" && !Array.isArray(v);
const optionalString = (v: unknown) => (typeof v === "string" ? v : undefined);
const optionalNumber = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;
const ARTIFACT_STATUSES: readonly ArtifactStatus[] = [
  "pending",
  "ready",
  "error",
];
const SUBAGENT_STATES: readonly SubagentState[] = [
  "queued",
  "running",
  "completed",
  "failed",
  "cancelled",
];
const member = <T extends string>(values: readonly T[], v: unknown): v is T =>
  typeof v === "string" && (values as readonly string[]).includes(v);

export function parseArtifact(v: unknown): ArtifactData | null {
  if (!record(v) || typeof v.id !== "string" || typeof v.filename !== "string")
    return null;
  return {
    id: v.id,
    filename: v.filename,
    mediaType: optionalString(v.mediaType) ?? "application/octet-stream",
    status: member(ARTIFACT_STATUSES, v.status) ? v.status : "ready",
    content: optionalString(v.content),
    url: optionalString(v.url),
  };
}
export function parseSubagent(v: unknown): SubagentData | null {
  if (
    !record(v) ||
    typeof v.id !== "string" ||
    typeof v.title !== "string" ||
    !member(SUBAGENT_STATES, v.state)
  )
    return null;
  return {
    id: v.id,
    title: v.title,
    state: v.state,
    task: optionalString(v.task),
    messages: Array.isArray(v.messages) ? v.messages : undefined,
  };
}
export const createArtifactData = (data: ArtifactData): CompatData => ({
  type: "data-artifact",
  id: data.id,
  data,
});
export const createSubagentData = (data: SubagentData): CompatData => ({
  type: "data-subagent",
  id: data.id,
  data,
});
export const parseUsage = (v: unknown): UsageData | null =>
  record(v)
    ? {
        input_tokens: optionalNumber(v.input_tokens),
        output_tokens: optionalNumber(v.output_tokens),
        reasoning_tokens: optionalNumber(v.reasoning_tokens),
        total_tokens: optionalNumber(v.total_tokens),
      }
    : null;
export const parseContext = (v: unknown): ContextData | null =>
  record(v)
    ? {
        current_tokens: optionalNumber(v.current_tokens),
        context_window: optionalNumber(v.context_window),
      }
    : null;
