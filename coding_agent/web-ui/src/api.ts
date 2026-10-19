// The launch capability arrives in the URL fragment; keep it tab-scoped.
export const token =
  location.hash.slice(1) || sessionStorage.getItem("symphony-token") || "";
if (location.hash) {
  sessionStorage.setItem("symphony-token", token);
  history.replaceState(null, "", location.pathname);
}
export async function api<T>(path: string, data?: object): Promise<T> {
  const r = await fetch("/api/" + path, {
    method: data ? "POST" : "GET",
    headers: {
      "X-Symphony-Token": token,
      ...(data ? { "Content-Type": "application/json" } : {}),
    },
    body: data ? JSON.stringify(data) : undefined,
  });
  const value: unknown = await r.json();
  if (!r.ok) {
    const message =
      value && typeof value === "object" && "error" in value
        ? String(value.error)
        : r.statusText;
    throw new Error(message);
  }
  return value as T;
}
export const withToken = (path: string) =>
  `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
