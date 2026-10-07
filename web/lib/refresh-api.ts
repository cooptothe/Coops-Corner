export interface RefreshStatus {
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_results: Record<string, string> | null;
  sports: { key: string; label: string }[];
  quota: Record<string, string> | null;
  cooldown_seconds: number;
  retry_after_seconds: number;
  attempts_today: number;
  daily_cap: number;
  credits_per_refresh: number;
  can_refresh: boolean;
}

async function call(
  method: "GET" | "POST",
  path: string,
  signal?: AbortSignal,
  sports?: string[],
): Promise<RefreshStatus> {
  const response = await fetch(`/api/refresh/v1/${path}`, {
    method,
    cache: "no-store",
    ...(sports && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sports }),
    }),
    signal: AbortSignal.any([
      ...(signal ? [signal] : []),
      // Provider capture plus ingestion can take a while.
      AbortSignal.timeout(method === "POST" ? 120000 : 30000),
    ]),
  });
  const body = await response.json().catch(() => {
    throw new Error("The refresh service returned an unreadable response.");
  });
  if (!response.ok) throw new Error(body.error ?? "Refresh failed.");
  return body as RefreshStatus;
}

export const refreshStatus = (signal?: AbortSignal) =>
  call("GET", "status", signal);
export const refreshOdds = (sports: string[]) =>
  call("POST", "odds", undefined, sports);

// The tools API rebuilds its catalog from the database; throws if the rebuild fails.
export async function reloadTools(): Promise<void> {
  const response = await fetch("/api/v1/catalog/reload", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: "{}",
    signal: AbortSignal.timeout(120000),
  });
  if (!response.ok)
    throw new Error("Odds were fetched, but the feed could not be rebuilt.");
}

let pageLoadReload: Promise<void> | null = null;
// Once per full page load, so a browser refresh also picks up newly stored odds.
export function reloadToolsOnce(): Promise<void> {
  pageLoadReload ??= reloadTools().catch(() => undefined);
  return pageLoadReload;
}
