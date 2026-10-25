import type { Capabilities, Game, Meta, Quote, ToolRow } from "./contracts";
import { sport } from "../../frontend/format.mjs";
import { MAIN_BOOKS } from "./bookmakers";
export type LiveKind = "ev" | "arbitrage" | "middle";
export type LiveStatus = "active" | "no_active_lines" | "unknown";
export type LiveMarket = "h2h" | "spreads" | "totals";
export interface LiveCandidate {
  row_id?: string;
  expires_at: number;
  kind: LiveKind;
  market: LiveMarket;
  line?: string;
  selection?: string;
  book?: string;
  decimal_odds?: string;
  fair_probability?: string;
  ev_percent?: string;
  profit_per_100?: string;
  best_profit_per_100?: string;
  worst_profit_per_100?: string;
  window?: [number | null, number | null][];
  legs?: {
    book: string;
    selection: string;
    line?: string;
    decimal_odds: string;
    stake: string;
  }[];
}
export interface LiveBook {
  book: string;
  active_market_count: number;
  status: string;
  markets: {
    key: LiveMarket;
    last_update: string;
    outcomes: { name: string; price: number; point?: number }[];
  }[];
}
export interface LiveEvent {
  game_status?: "in_play" | "paused" | "finished" | "not_started" | "unknown";
  game_status_detail?: string;
  game_status_source?: "espn" | null;
  game_status_updated_at?: string | null;
  game_status_expires_at?: number;
  commence_time?: string;
  tool_rows?: ToolRow[];
  quotes?: Quote[];
  id: string;
  sport_key: string;
  home_team: string;
  away_team: string;
  status: LiveStatus;
  is_suspended: boolean | null;
  active_market_count: number;
  books: LiveBook[];
  opportunities: LiveCandidate[];
}
export interface LiveFeed {
  format: "corner.live_odds/1";
  devig_method?: string;
  as_of: string;
  enabled: boolean;
  state: string;
  events: LiveEvent[];
  live_credits_accounted?: number;
  monthly_subcap: number;
  collection_intervals_seconds?: { standard: number; exchange: number };
}
export interface LiveRow {
  market: LiveMarket;
  id: string;
  event: LiveEvent;
  candidate: LiveCandidate | null;
}
export function gameState(event: LiveEvent, now = Date.now() / 1000): string {
  return event.game_status_source === "espn" &&
    (event.game_status_expires_at ?? 0) > now
    ? (event.game_status ?? "unknown")
    : "unknown";
}
export function matchesLiveState(
  event: LiveEvent,
  status: string,
  now = Date.now() / 1000,
): boolean {
  return (
    !status ||
    (status === "playing"
      ? gameState(event, now) === "in_play"
      : status === "paused"
        ? gameState(event, now) === "paused"
        : event.status === status)
  );
}
export function liveRows(
  feed: LiveFeed,
  kind: LiveKind,
  market: LiveMarket,
  sport: string,
  status: string,
): LiveRow[] {
  return feed.events
    .filter(
      (e) => (!sport || e.sport_key === sport) && matchesLiveState(e, status),
    )
    .flatMap<LiveRow>((event) => {
      const candidates = event.opportunities.filter(
        (c) => c.kind === kind && c.market === market,
      );
      return candidates.length
        ? candidates.map((c) => ({
            id: [
              event.id,
              c.kind,
              c.market,
              c.line,
              c.selection,
              c.book,
              c.legs
                ?.map((l) => `${l.book}:${l.selection}:${l.line}`)
                .join("|"),
            ].join(":"),
            event,
            market,
            candidate: c,
          }))
        : [{ id: `${event.id}:availability`, event, market, candidate: null }];
    });
}
export function liveAmerican(decimal: number): string {
  if (!Number.isFinite(decimal) || decimal <= 1) return "—";
  const value =
    decimal >= 2
      ? Math.round((decimal - 1) * 100)
      : Math.round(-100 / (decimal - 1));
  return value > 0 ? `+${value}` : String(value);
}
export function liveRange(
  scroll: number,
  count: number,
  height = 560,
  rowHeight = 112,
) {
  const start = Math.min(
      Math.max(0, count - Math.ceil(height / rowHeight)),
      Math.max(0, Math.floor(scroll / rowHeight) - 4),
    ),
    end = Math.min(count, Math.ceil((scroll + height) / rowHeight) + 4);
  return {
    start,
    end,
    top: start * rowHeight,
    bottom: Math.max(0, (count - end) * rowHeight),
  };
}
export function liveFresh(
  candidate: LiveCandidate,
  serverAsOf: string,
  elapsedMs: number,
): boolean {
  return (
    elapsedMs >= 0 &&
    elapsedMs <= 20000 &&
    candidate.expires_at > Date.parse(serverAsOf) / 1000 + elapsedMs / 1000
  );
}

// The standard feed renderers consume the same contract in both modes.
// Only fresh live candidates are supplied; never fall back to pregame odds.
export function liveProduct(feed: LiveFeed, status: string, elapsed: number) {
  const events = feed.events.filter((e) =>
    matchesLiveState(e, status, Date.parse(feed.as_of) / 1000 + elapsed / 1000),
  );
  const quotes = new Map<string, Quote>();
  const rows: ToolRow[] = [];
  const games: Game[] = events.map((e) => {
    const eligible = new Set(
      e.opportunities
        .filter((c) => liveFresh(c, feed.as_of, elapsed))
        .map((c) => c.row_id),
    );
    rows.push(...(e.tool_rows ?? []).filter((r) => eligible.has(r.id)));
    for (const q of e.quotes ?? []) quotes.set(q.id, q);
    return {
      id: e.id,
      sport_key: e.sport_key,
      competition: sport(e.sport_key),
      name: `${e.away_team} at ${e.home_team}`,
      starts_at: e.commence_time ?? "",
      scope: "full_game",
      market_keys: ["h2h", "spreads", "totals"],
      quote_count: e.quotes?.length ?? 0,
      phase: "unknown",
    };
  });
  const caps: Capabilities = {
    market_keys: ["h2h", "spreads", "totals"],
    tools: ["positive_ev", "arbitrage", "middle"],
    sports: [...new Set(games.map((g) => g.sport_key))],
    books: MAIN_BOOKS.map((b) => ({ ...b, commission: null })),
  };
  const meta: Meta = {
    format: "corner.product_api/1",
    data_mode: "database",
    snapshot_id: `live:${feed.as_of}:${feed.devig_method ?? "current"}`,
    captured_at: feed.as_of,
    production_authorized: false,
    availability_verified: false,
  };
  return { data: { caps, games, quotes: [...quotes.values()], meta }, rows };
}

// An empty data shell keeps controls mounted before the first response; it contains no odds.
export const EMPTY_LIVE_FEED: LiveFeed = {
  format: "corner.live_odds/1",
  as_of: "1970-01-01T00:00:00Z",
  enabled: false,
  state: "loading",
  monthly_subcap: 500000,
  events: [],
};
