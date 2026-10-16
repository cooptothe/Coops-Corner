import { notifyUnauthorized } from "./auth-api";
import type { QuoteLinks } from "./bet-links";

export interface RefreshStatus {
  manual_fetch_enabled?: boolean;
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
  if (response.status === 401) notifyUnauthorized();
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
  if (response.status === 401) notifyUnauthorized();
  if (!response.ok)
    throw new Error("Odds were fetched, but the feed could not be rebuilt.");
}

export interface PropMarketInfo {
  key: string;
  label: string;
  group: string;
  kind: "two_way" | "yes_only";
  default: boolean;
}
export interface PropBet {
  source_ids?: {
    event?: string | null;
    market?: string | null;
    outcome?: string | null;
  } | null;
  id: string;
  event_id: string;
  sport_key: string;
  home: string;
  away: string;
  starts_at: string;
  market_key: string;
  market_label: string;
  group: string;
  player: string;
  point: string | null;
  side: string;
  book: string;
  price: string;
  ev: string;
  fair_probability: string;
  sharps: string[];
  market_width_cents?: string | null;
  reference_weights?: Record<string, string>;
  reference_weight_version?: string;
  observed_at: string | null;
  links?: QuoteLinks | null;
}
export interface PropsStatus {
  manual_fetch_enabled?: boolean;
  sports: { key: string; label: string }[];
  markets: Record<string, PropMarketInfo[]>;
  default_events: number;
  max_events: number;
  // Fetches older than this stop counting, so the feed only holds current prices.
  max_age_seconds: number;
  last_success_at: string | null;
  bets?: PropBet[];
  // Set by a fetch: what happened, whether any game was fetched, and why it stopped early.
  refreshed?: boolean;
  stopped?: string | null;
  message?: string;
  // Bets now available for the fetched league (priced against two or more sharp books).
  bets_found?: number;
}

async function propsCall(
  method: "GET" | "POST",
  body?: unknown,
  signal?: AbortSignal,
): Promise<PropsStatus> {
  const response = await fetch("/api/refresh/v1/props", {
    method,
    cache: "no-store",
    ...(body !== undefined && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    signal: AbortSignal.any([
      ...(signal ? [signal] : []),
      AbortSignal.timeout(method === "POST" ? 180000 : 30000),
    ]),
  });
  const data = await response.json().catch(() => {
    throw new Error("The refresh service returned an unreadable response.");
  });
  if (response.status === 401) notifyUnauthorized();
  if (!response.ok) throw new Error(data.error ?? "Request failed.");
  return data as PropsStatus;
}
export const loadProps = (signal?: AbortSignal) =>
  propsCall("GET", undefined, signal);
export const refreshProps = (
  sport: string,
  markets: string[],
  max_events: number,
) => propsCall("POST", { sport, markets, max_events });

let pageLoadReload: Promise<void> | null = null;
// Once per full page load, so a browser refresh also picks up newly stored odds.
export function reloadToolsOnce(): Promise<void> {
  pageLoadReload ??= reloadTools().catch(() => undefined);
  return pageLoadReload;
}
