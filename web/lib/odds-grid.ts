import type { MarketKey, Quote } from "./contracts";

export type GridMarket = Extract<MarketKey, "spreads" | "h2h" | "totals">;
export const GRID_MARKETS: { key: GridMarket; label: string }[] = [
  { key: "spreads", label: "Spreads" },
  { key: "h2h", label: "Moneyline" },
  { key: "totals", label: "Totals" },
];

export interface Price {
  quoteId: string;
  decimal: number;
  point: number | null;
}
export type Cell = Partial<Record<string, Price>>;
// gameId -> bookId -> side -> price
export type Board = Map<string, Map<string, Cell>>;

export const sidesFor = (market: GridMarket, withDraw: boolean): string[] =>
  market === "totals"
    ? ["over", "under"]
    : market === "h2h" && withDraw
      ? ["away", "draw", "home"]
      : ["away", "home"];

const parse = (v: string | null): number | null => {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

// A book may quote several alternate lines; keep the one nearest even money.
export function buildBoard(quotes: Quote[], market: GridMarket): Board {
  const pairs = new Map<string, Quote[]>();
  for (const q of quotes) {
    if (q.market_key !== market) continue;
    const key = `${q.game_id}|${q.sportsbook_id}|${q.contract_id}`;
    const list = pairs.get(key);
    if (list) list.push(q);
    else pairs.set(key, [q]);
  }
  const chosen = new Map<string, { gap: number; qs: Quote[] }>();
  for (const qs of pairs.values()) {
    const odds = qs.map((q) => Number(q.decimal_odds));
    if (odds.some((o) => !(o > 1))) continue;
    const gap = Math.abs(Math.min(...odds) - Math.max(...odds));
    const key = `${qs[0].game_id}|${qs[0].sportsbook_id}`;
    const best = chosen.get(key);
    if (!best || gap < best.gap) chosen.set(key, { gap, qs });
  }
  const board: Board = new Map();
  for (const { qs } of chosen.values()) {
    const game = board.get(qs[0].game_id) ?? new Map<string, Cell>();
    const cell: Cell = {};
    for (const q of qs)
      cell[q.side] = {
        quoteId: q.id,
        decimal: Number(q.decimal_odds),
        point: parse(q.point),
      };
    game.set(qs[0].sportsbook_id, cell);
    board.set(qs[0].game_id, game);
  }
  return board;
}

// Positive when `a` is a better price than `b` for the bettor.
export function compareValue(
  market: GridMarket,
  side: string,
  a: Price,
  b: Price,
): number {
  if (a.point != null && b.point != null && a.point !== b.point) {
    const larger = market === "totals" && side === "over" ? -1 : 1;
    return (a.point - b.point) * larger;
  }
  return a.decimal - b.decimal;
}

export function bestQuoteId(
  market: GridMarket,
  side: string,
  prices: Price[],
): string | null {
  if (prices.length < 2) return null;
  let best = prices[0];
  for (const p of prices.slice(1))
    if (compareValue(market, side, p, best) > 0) best = p;
  const tied = prices.every((p) => compareValue(market, side, p, best) === 0);
  return tied ? null : best.quoteId;
}

export function movement(
  market: GridMarket,
  side: string,
  prev: Price | undefined,
  next: Price | undefined,
): "up" | "down" | null {
  if (!prev || !next) return null;
  const c = compareValue(market, side, next, prev);
  return c > 0 ? "up" : c < 0 ? "down" : null;
}
