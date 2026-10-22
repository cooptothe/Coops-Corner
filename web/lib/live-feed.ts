export type LiveKind = "ev" | "arbitrage" | "middle";
export type LiveStatus = "active" | "no_active_lines" | "unknown";
export type LiveMarket = "h2h" | "spreads" | "totals";
export interface LiveCandidate {
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
  as_of: string;
  enabled: boolean;
  state: string;
  events: LiveEvent[];
  live_credits_accounted?: number;
  monthly_subcap: number;
}
export interface LiveRow {
  market: LiveMarket;
  id: string;
  event: LiveEvent;
  candidate: LiveCandidate | null;
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
      (e) =>
        (!sport || e.sport_key === sport) && (!status || e.status === status),
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
