import type { QuoteLinks } from "./bet-links";
import type { Game, Quote } from "./contracts";
import { quoteRef } from "./slip";

export type LineMarket = "spreads" | "totals" | "h2h";
export const LINE_MARKETS: LineMarket[] = ["spreads", "totals", "h2h"];

export interface BestPrice {
  ref?: ReturnType<typeof quoteRef>;
  quoteId: string;
  bookId: string;
  decimal: number;
  point: number | null;
  links?: QuoteLinks | null;
}
// The main line of one market: the best price on each side, all at the same line.
export interface MainLine {
  // Sportsbooks pricing both sides of this line.
  books: number;
  sides: Record<string, BestPrice>;
}
export type GameLines = Partial<Record<LineMarket, MainLine>>;

const REQUIRED: Record<LineMarket, string[]> = {
  spreads: ["away", "home"],
  totals: ["over", "under"],
  h2h: ["away", "home"],
};
// Soccer moneylines are three-way.
const OPTIONAL: Record<LineMarket, string[]> = {
  spreads: [],
  totals: [],
  h2h: ["draw"],
};

// Reference (sharp) books set the market but are not books a typical bettor can use.
export const REFERENCE_BOOKS = new Set([
  "pinnacle",
  "betfair_ex_uk",
  "prophetx",
  "kalshi",
]);

const num = (v: string | null): number | null => {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

interface Candidate {
  contractId: string;
  sides: Record<string, BestPrice>;
  books: number;
  gap: number;
}

function candidate(
  contractId: string,
  market: LineMarket,
  quotes: Quote[],
): Candidate | null {
  const best: Record<string, BestPrice> = {};
  const byBook = new Map<string, Record<string, number>>();
  for (const q of quotes) {
    const decimal = Number(q.decimal_odds);
    if (!(decimal > 1)) continue;
    const sides = byBook.get(q.sportsbook_id) ?? {};
    sides[q.side] = decimal;
    byBook.set(q.sportsbook_id, sides);
    const held = best[q.side];
    // Highest price wins; a tie goes to the lexically first book, so the result is stable.
    if (
      !held ||
      decimal > held.decimal ||
      (decimal === held.decimal && q.sportsbook_id < held.bookId)
    )
      best[q.side] = {
        ref: quoteRef(q),
        quoteId: q.id,
        bookId: q.sportsbook_id,
        decimal,
        point: num(q.point),
        links: q.links ?? null,
      };
  }
  const [a, b] = REQUIRED[market];
  if (!best[a] || !best[b]) return null;
  let books = 0;
  let gapSum = 0;
  for (const sides of byBook.values()) {
    if (sides[a] && sides[b]) {
      books += 1;
      gapSum += Math.abs(sides[a] - sides[b]);
    }
  }
  const sides: Record<string, BestPrice> = { [a]: best[a], [b]: best[b] };
  for (const extra of OPTIONAL[market])
    if (best[extra]) sides[extra] = best[extra];
  return {
    contractId,
    sides,
    books,
    gap: books ? gapSum / books : Infinity,
  };
}

// The main line is the one most books quote on both sides; a tie goes to the line
// whose two sides are closest to even money, then to the lexically first contract.
function pickMain(candidates: Candidate[]): Candidate | null {
  let main: Candidate | null = null;
  for (const c of candidates) {
    if (
      !main ||
      c.books > main.books ||
      (c.books === main.books && c.gap < main.gap) ||
      (c.books === main.books &&
        c.gap === main.gap &&
        c.contractId < main.contractId)
    )
      main = c;
  }
  return main;
}

// Best main-line prices per game and market, from only the sportsbooks `allowed` admits.
export function buildGameLines(
  quotes: Quote[],
  allowed: (bookId: string) => boolean,
): Map<string, GameLines> {
  const groups = new Map<string, Map<string, Quote[]>>();
  for (const q of quotes) {
    if (!allowed(q.sportsbook_id)) continue;
    if (!LINE_MARKETS.includes(q.market_key as LineMarket)) continue;
    const key = `${q.game_id}|${q.market_key}`;
    const contracts = groups.get(key) ?? new Map<string, Quote[]>();
    const list = contracts.get(q.contract_id);
    if (list) list.push(q);
    else contracts.set(q.contract_id, [q]);
    groups.set(key, contracts);
  }
  const out = new Map<string, GameLines>();
  for (const [key, contracts] of groups) {
    const [gameId, market] = key.split("|") as [string, LineMarket];
    const candidates = [...contracts]
      .map(([id, qs]) => candidate(id, market, qs))
      .filter((c): c is Candidate => c !== null);
    const main = pickMain(candidates);
    if (!main) continue;
    const lines = out.get(gameId) ?? {};
    lines[market] = { books: main.books, sides: main.sides };
    out.set(gameId, lines);
  }
  return out;
}

// Calendar day in the app's display zone, so "today" matches the times shown.
const ZONE = "America/Chicago";
const dayFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
export const dayKey = (iso: string | number | Date) =>
  dayFormat.format(new Date(iso));

const timeFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: ZONE,
  hour: "numeric",
  minute: "2-digit",
});
export const timeLabel = (iso: string) => timeFormat.format(new Date(iso));

const headingFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: ZONE,
  weekday: "long",
  month: "long",
  day: "numeric",
});
export function dayHeading(key: string, now: number = Date.now()): string {
  const noon = new Date(`${key}T12:00:00Z`);
  const label = headingFormat.format(noon);
  const today = dayKey(now);
  if (key === today) return `Today · ${label}`;
  if (key === dayKey(now + 86400000)) return `Tomorrow · ${label}`;
  return label;
}

// Hide an unpriced alias only when the identical fixture has a usable main-line
// board elsewhere. Never merge quote/contract IDs or infer identity from teams
// alone: rematches, doubleheaders, other leagues and opposite roles stay separate.
export function scheduleFixtures(games: Game[], quotes: Quote[]): Game[] {
  const boards = buildGameLines(quotes, () => true);
  const normalize = (value: string) =>
    value.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();
  const key = (game: Game): string => {
    const start = Date.parse(game.starts_at);
    return !Number.isFinite(start) || !game.name.trim()
      ? JSON.stringify(["id", game.id])
      : JSON.stringify([
          game.sport_key,
          game.scope,
          normalize(game.competition),
          start,
          normalize(game.name),
        ]);
  };
  const priced = new Set(games.filter((game) => boards.has(game.id)).map(key));
  const seen = new Set<string>();
  return games.filter((game) => {
    if (seen.has(game.id)) return false;
    seen.add(game.id);
    return boards.has(game.id) || !priced.has(key(game));
  });
}
