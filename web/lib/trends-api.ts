import { notifyUnauthorized } from "./auth-api";
import type { QuoteLinks } from "./bet-links";

export interface TrendContract {
  event_id?: string;
  market_label?: string;
  commission?: string;
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
  opponent?: string;
  team?: string;
  history_games?: TrendReport["games"];
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
    workload: string | null;
    source_url: string | null;
    season: number;
  }[];
  model_probability: number | null;
  model_ev: number | null;
  historical_sensitivity_ev: number | null;
  break_even_probability: number;
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
