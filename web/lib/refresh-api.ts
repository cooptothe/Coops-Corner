import { parsePropsStatus } from "./props-response";
import { announceOddsUpdated } from "./odds-updates";
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
  credits_per_sport?: number;
  additional_max_events_per_league?: number | null;
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
  if (
    response.status === 401 ||
    (response.status === 403 && body.code === "membership_required")
  )
    notifyUnauthorized();
  if (!response.ok) throw new Error(body.error ?? "Refresh failed.");
  return body as RefreshStatus;
}

export const refreshStatus = (signal?: AbortSignal) =>
  call("GET", "status", signal);
export const refreshOdds = (sports: string[]) =>
  call("POST", "odds", undefined, sports);

// The tools API rebuilds its catalog from the database; throws if the rebuild fails.
export async function reloadTools(announce = true): Promise<void> {
  const response = await fetch("/api/v1/catalog/reload", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: "{}",
    signal: AbortSignal.timeout(120000),
  });
  if (response.status === 401) notifyUnauthorized();
  if (!response.ok)
    throw new Error(
      "Odds were fetched, but the shared feeds could not be rebuilt. Reload the app before fetching again.",
    );
  if (announce) announceOddsUpdated();
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
  net_decimal_odds?: string;
  commission_rate?: string;
  probability_basis?: string;
  dfs_reference_books?: string[];
  dfs_assumption?: string | null;
  reference_policy?: string;
  calibration_status?: string;
  settlement_basis?: string;
  assumed_margin?: string | null;
  stress_margin?: string | null;
  sharps: string[];
  market_width_cents?: string | null;
  reference_weights?: Record<string, string>;
  reference_weight_version?: string;
  devig_comparisons?:
    import("../components/devig-comparison").DevigResult[] | null;
  allocation_sensitivity?: {
    probability_min: string;
    probability_max: string;
    ev_min: string;
    ev_max: string;
    confidence_interval: false;
    empirically_calibrated: false;
  } | null;
  observed_at: string | null;
  links?: QuoteLinks | null;
}
export interface PropsStatus {
  invalid_bets?: number;
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
  oneSidedMargin?: string,
): Promise<PropsStatus> {
  const query =
    oneSidedMargin === undefined
      ? ""
      : `?${new URLSearchParams({ one_sided_margin: oneSidedMargin })}`;
  const response = await fetch(`/api/refresh/v1/props${query}`, {
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
  if (
    response.status === 401 ||
    (response.status === 403 && data.code === "membership_required")
  )
    notifyUnauthorized();
  if (!response.ok) throw new Error(data.error ?? "Request failed.");
  return parsePropsStatus(data);
}
export const loadProps = (signal?: AbortSignal, oneSidedMargin?: string) =>
  propsCall("GET", undefined, signal, oneSidedMargin);
export const refreshProps = async (
  sport: string,
  markets: string[],
  max_events: number,
) => {
  const result = await propsCall("POST", { sport, markets, max_events });
  // Publish the captured props to every tool before declaring the update done.
  // This only re-reads retained quotes: it never requests provider odds.
  await reloadTools();
  return result;
};

let pageLoadReload: Promise<void> | null = null;
// Once per full page load, so a browser refresh also picks up newly stored odds.
export function reloadToolsOnce(): Promise<void> {
  pageLoadReload ??= reloadTools(false).catch(() => undefined);
  return pageLoadReload;
}
