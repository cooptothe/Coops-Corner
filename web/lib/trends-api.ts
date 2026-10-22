import { notifyUnauthorized } from "./auth-api";
import type { QuoteLinks } from "./bet-links";

export interface TrendContract {
  quote_status?: "current" | "stale" | "past_event";
  quote_expires_at?: string;
  settlement_point?: string | null;
  projection_plan?: { method: string; requires: string[] };
  event_id?: string;
  market_label?: string;
  commission?: string | null;
  fee_status?: string;
  price_kind?: "decimal" | "indicative";
  source_ids?: { market?: string | null; outcome?: string | null } | null;
  starts_at?: string;
  observed_at?: string | null;
  links?: QuoteLinks | null;
  id: string;
  bet_id: string;
  sport_key: string;
  player: string;
  market_key: string;
  home: string;
  away: string;
  side: string;
  point: string;
  price: string;
  book: string;
}
export interface TrendSummary {
  games: number;
  wins: number;
  losses: number;
  pushes: number;
  hit_rate: number | null;
  mean: number | null;
  median: number | null;
  historical_interval: [number, number] | null;
}
export interface TrendReport {
  projection?: {
    status: string;
    method: string;
    reason?: string;
    games?: number;
    projected_mean?: number;
    probability?: number;
    push_probability?: number;
    model_ev?: number | null;
    sensitivity_ev?: [number, number] | null;
    predictive_10_90?: [number, number] | null;
    live_feed_eligible: false;
    edge_validated: false;
    models?: {
      method: string;
      win: number;
      push: number;
      loss: number;
      ev: number | null;
    }[];
    assumptions?: string[];
  };
  opponent?: string;
  team?: string;
  history_games?: TrendReport["games"];
  season_games?: TrendReport["games"];
  workload_label: string;
  availability_url: string;
  historical_replay: {
    held_out_games: number;
    brier: number | null;
    log_loss: number | null;
    edge_validated: false;
  };
  player: string;
  windows: Record<string, TrendSummary>;
  baseline: TrendSummary;
  matchup: TrendSummary;
  venue: TrendSummary;
  flags: string[];
  games: {
    id: string;
    date: string;
    value: string;
    opponent: string;
    home: boolean | null;
    game_result?: "W" | "L" | "T";
    workload: string | null;
    source_url: string | null;
    season: number;
  }[];
  model_probability: number | null;
  model_ev: number | null;
  historical_sensitivity_ev: number | null;
  break_even_probability: number | null;
  research_signal: boolean;
  workload_change: number | null;
  stats_fetched_at: string;
  news_fetched_at: string | null;
  news_status: string;
  news: { headline: string; url: string; published: string }[];
  coverage: string;
  source: string;
  contract: TrendContract;
}
export async function trendsRequest<T>(
  path: string,
  signal: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/refresh/v1/props/trends${path}`, {
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(90000)]),
  }).catch(() => {
    throw new Error(
      "Player research is temporarily unavailable. Please try again.",
    );
  });
  if (response.status === 401) notifyUnauthorized();
  const data = await response.json().catch(() => null);
  if (response.status === 403 && data?.code === "membership_required")
    notifyUnauthorized();
  if (!response.ok)
    throw new Error(
      typeof data?.error === "string"
        ? data.error
        : "Player research could not be loaded. Please try again.",
    );
  if (!data)
    throw new Error("Player research could not be loaded. Please try again.");
  return data as T;
}

export async function loadTrendOptions(
  signal: AbortSignal,
): Promise<{ contracts: TrendContract[] }> {
  const result: TrendContract[] = [];
  const seen = new Set<string>();
  let offset = 0,
    snapshot: string | undefined,
    total: number | undefined;
  for (let page = 0; page < 100; page++) {
    const data = await trendsRequest<{
      contracts: TrendContract[];
      snapshot_id: string;
      total: number;
      offset: number;
      next_offset: number | null;
    }>(`/options?offset=${offset}&limit=1000`, signal);
    if (signal.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    if (
      snapshot !== undefined &&
      (data.snapshot_id !== snapshot || data.total !== total)
    )
      throw Error(
        "Stored prices changed while loading. Please refresh The Lab.",
      );
    snapshot = data.snapshot_id;
    total = data.total;
    if (
      !Array.isArray(data.contracts) ||
      data.offset !== offset ||
      !Number.isInteger(total) ||
      total < 0
    )
      throw Error("Research page was invalid.");
    for (const item of data.contracts) {
      if (seen.has(item.id)) throw Error("Duplicate research quote.");
      seen.add(item.id);
      result.push(item);
    }
    if (data.next_offset === null) {
      if (result.length !== total)
        throw Error("Research coverage was incomplete.");
      return { contracts: result };
    }
    if (!Number.isInteger(data.next_offset) || data.next_offset <= offset)
      throw Error("Research page cursor was invalid.");
    offset = data.next_offset;
  }
  throw Error(
    "Research coverage exceeds the current page limit; no partial list was accepted.",
  );
}
