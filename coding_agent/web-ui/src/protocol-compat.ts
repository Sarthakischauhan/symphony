// chat@0.0.1 imports these helpers, but protocol@0.0.1 and @0.0.2
// omit them. Keep this backend-neutral bridge until upstream republishes.
export * from "@sarchauhan/protocol-original";
const record = (v: unknown): v is Record<string, any> =>
  !!v && typeof v === "object" && !Array.isArray(v);
export function parseArtifact(v: unknown): Record<string, any> | null {
  if (!record(v) || typeof v.id !== "string" || typeof v.filename !== "string")
    return null;
  return {
    ...v,
    mediaType:
      typeof v.mediaType === "string"
        ? v.mediaType
        : "application/octet-stream",
    status: v.status || "ready",
  };
}
export function parseSubagent(v: unknown) {
  if (
    !record(v) ||
    typeof v.id !== "string" ||
    typeof v.title !== "string" ||
    !["queued", "running", "completed", "failed", "cancelled"].includes(v.state)
  )
    return null;
  return v;
}
export const createArtifactData = (data: any) => ({
  type: "data-artifact",
  id: data.id,
  data,
});
export const createSubagentData = (data: any) => ({
  type: "data-subagent",
  id: data.id,
  data,
});
export const parseUsage = (v: unknown) => (record(v) ? v : null);
export const parseContext = (v: unknown) => (record(v) ? v : null);
