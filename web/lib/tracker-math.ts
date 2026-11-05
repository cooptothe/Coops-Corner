// Pure money and performance math for the tracker. Everything is whole cents, derived from the ledger
// (bets + cash entries); nothing here is stored, so edits and deletes can never leave totals stale.
import { sport as sportLabel } from "../../frontend/format.mjs";
import type { CashEntry, TrackerBet, TrackerState } from "./tracker-api";

export const VAULT = "vault";

const BOOK_LABELS: Record<string, string> = {
  vault: "Vault (bank)",
  betonlineag: "BetOnline",
  bovada: "Bovada",
  draftkings: "DraftKings",
  fanduel: "FanDuel",
  betmgm: "BetMGM",
  betrivers: "BetRivers",
  caesars: "Caesars",
  williamhill_us: "Caesars",
  espnbet: "theScore Bet",
  thescore_bet: "theScore Bet",
  novig: "Novig",
  fanatics: "Fanatics",
  hardrockbet: "Hard Rock Bet",
  hard_rock_bet: "Hard Rock Bet",
  bet365: "bet365",
  pinnacle: "Pinnacle",
  prophetx: "ProphetX",
  kalshi: "Kalshi",
  betfair: "Betfair",
};
export const COMMON_BOOKS = [
  "betonlineag",
  "bovada",
  "draftkings",
  "fanduel",
  "betmgm",
  "betrivers",
  "caesars",
  "espnbet",
  "novig",
  "fanatics",
  "hardrockbet",
  "bet365",
];

export function bookCode(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  if (slug === "betonline") return "betonlineag";
  if (BOOK_LABELS[slug]) return slug;
  const squashed = slug.replace(/_/g, "");
  return (
    Object.keys(BOOK_LABELS).find((k) => k.replace(/_/g, "") === squashed) ??
    (slug || "other")
  );
}

export function bookLabel(code: string): string {
  return (
    BOOK_LABELS[code] ??
    code.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

const LEAGUE_LABELS: Record<string, string> = {
  americanfootball_nfl: "NFL",
  americanfootball_ncaaf: "NCAAF",
  basketball_nba: "NBA",
  basketball_ncaab: "NCAAB",
  basketball_wncaab: "WNCAAB",
  basketball_wnba: "WNBA",
  baseball_mlb: "MLB",
  icehockey_nhl: "NHL",
  soccer_epl: "Premier League",
  soccer_spain_la_liga: "La Liga",
  soccer_germany_bundesliga: "Bundesliga",
  soccer_italy_serie_a: "Serie A",
  soccer_france_ligue_one: "Ligue 1",
  soccer_usa_mls: "MLS",
  soccer_uefa_champs_league: "Champions League",
  tennis_atp: "ATP",
  tennis_wta: "WTA",
  mma_mixed_martial_arts: "MMA",
};
const ABBR: Record<string, string> = {
  betonlineag: "BOL",
  bovada: "BOV",
  draftkings: "DK",
  fanduel: "FD",
  betmgm: "MGM",
  betrivers: "BR",
  caesars: "CZR",
  williamhill_us: "CZR",
  espnbet: "TS",
  thescore_bet: "TS",
  novig: "NV",
  fanatics: "FAN",
  hardrockbet: "HR",
  hard_rock_bet: "HR",
  bet365: "365",
  pinnacle: "PIN",
  prophetx: "PX",
  kalshi: "KAL",
  vault: "BANK",
};
export function bookAbbr(code: string): string {
  return (
    ABBR[code] ??
    bookLabel(code)
      .split(/\s+/)
      .map((w) => w[0])
      .join("")
      .slice(0, 3)
      .toUpperCase()
  );
}

export const STRATEGY_LABEL: Record<string, string> = {
  ev: "+EV",
  arbitrage: "Arb",
  middle: "Middle",
  promo: "Promo",
  prop: "Prop",
  manual: "Manual",
  parlay: "Parlay",
};

export const LEAGUE_KEYS = Object.keys(LEAGUE_LABELS);
export function leagueLabel(sportKey: string): string {
  if (!sportKey) return "Other";
  if (/^tennis_(atp|wta)_/.test(sportKey)) return sportLabel(sportKey);
  return (
    LEAGUE_LABELS[sportKey] ??
    sportKey
      .split("_")
      .slice(1)
      .join(" ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

// ---- single bets ------------------------------------------------------------------------------

export const isSettled = (b: TrackerBet) => b.status !== "pending";
// Cash that leaves the book when the bet is placed. A bonus bet costs nothing.
export const outlay = (b: TrackerBet) =>
  b.stake_type === "cash" ? b.stake_cents : 0;

export function profit(b: TrackerBet): number | null {
  return isSettled(b) && b.returned_cents != null
    ? b.returned_cents - outlay(b)
    : null;
}

// The cash a win brings back beyond what the bet cost: winnings for cash and bonus bets, and the whole
// payout for site credit (which cost nothing).
export const toWin = (b: TrackerBet) =>
  Math.round(
    b.stake_cents * (Number(b.odds) - (b.stake_type === "credit" ? 0 : 1)),
  );

export const dollars = (cents: number) => (cents / 100).toFixed(2);
// "+$12.50" / "-$3.00" / "$0.00"
export const signedDollars = (cents: number) => {
  const text = `${cents < 0 ? "-" : ""}$${Math.abs(cents / 100)
    .toFixed(2)
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
  return cents > 0 ? `+${text}` : text;
};
export const signedPercent = (ratio: number | null, places = 1) =>
  ratio == null
    ? "—"
    : `${ratio > 0 ? "+" : ""}${(ratio * 100).toFixed(places)}%`;
export const parseDollars = (text: string): number | null => {
  const t = text.trim().replace(/^\$/, "").replace(/,/g, "");
  if (!/^-?\d{1,12}(\.\d{1,2})?$/.test(t)) return null;
  return Math.round(Number(t) * 100);
};

// ---- balances ---------------------------------------------------------------------------------

export interface BookBalance {
  book: string;
  liquid: number;
  pending: number;
}
export interface Totals {
  liquid: number;
  pending: number;
  bankroll: number;
}

export function bookBalances(state: TrackerState): BookBalance[] {
  const map = new Map<string, BookBalance>();
  const at = (book: string) => {
    let row = map.get(book);
    if (!row) map.set(book, (row = { book, liquid: 0, pending: 0 }));
    return row;
  };
  for (const c of state.cash) {
    if (c.kind === "deposit" || c.kind === "adjustment")
      at(c.book).liquid += c.amount_cents;
    else if (c.kind === "withdrawal") at(c.book).liquid -= c.amount_cents;
    else {
      at(c.book).liquid -= c.amount_cents;
      at(c.to_book ?? c.book).liquid += c.amount_cents;
    }
  }
  for (const b of state.bets) {
    const row = at(b.book);
    row.liquid -= outlay(b);
    if (b.status === "pending") row.pending += outlay(b);
    else row.liquid += b.returned_cents ?? 0;
  }
  return [...map.values()].sort(
    (a, b) => b.liquid + b.pending - (a.liquid + a.pending),
  );
}

export function totals(rows: BookBalance[]): Totals {
  const liquid = rows.reduce((n, r) => n + r.liquid, 0);
  const pending = rows.reduce((n, r) => n + r.pending, 0);
  return { liquid, pending, bankroll: liquid + pending };
}

// ---- the unified ledger -----------------------------------------------------------------------

export type LedgerKind =
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "BOOK_TRANSFER"
  | "ADJUSTMENT"
  | "WAGER_DEDUCTION"
  | "WAGER_PAYOUT";
export interface LedgerRow {
  id: string;
  at: string;
  kind: LedgerKind;
  book: string;
  toBook: string | null;
  // The cash moved at `book` (signed: negative leaves it).
  amount: number;
  // Net bankroll after this entry.
  running: number;
  memo: string;
  cashId: string | null;
}

const RANK: Record<LedgerKind, number> = {
  DEPOSIT: 0,
  ADJUSTMENT: 0,
  BOOK_TRANSFER: 1,
  WAGER_DEDUCTION: 2,
  WAGER_PAYOUT: 3,
  WITHDRAWAL: 4,
};

export function ledger(state: TrackerState): LedgerRow[] {
  const raw: Omit<LedgerRow, "running">[] = [];
  const delta = new Map<string, number>();
  for (const c of state.cash) {
    const kind: LedgerKind =
      c.kind === "deposit"
        ? "DEPOSIT"
        : c.kind === "withdrawal"
          ? "WITHDRAWAL"
          : c.kind === "transfer"
            ? "BOOK_TRANSFER"
            : "ADJUSTMENT";
    const signed = c.kind === "withdrawal" ? -c.amount_cents : c.amount_cents;
    delta.set(`c:${c.id}`, c.kind === "transfer" ? 0 : signed);
    raw.push({
      id: `c:${c.id}`,
      at: c.occurred_at,
      kind,
      book: c.book,
      toBook: c.to_book,
      amount: c.kind === "transfer" ? c.amount_cents : signed,
      memo: c.note,
      cashId: c.id,
    });
  }
  for (const b of state.bets) {
    if (outlay(b) > 0) {
      delta.set(`p:${b.id}`, 0);
      raw.push({
        id: `p:${b.id}`,
        at: b.placed_at,
        kind: "WAGER_DEDUCTION",
        book: b.book,
        toBook: null,
        amount: -outlay(b),
        memo: `${b.selection} · ${b.matchup}`,
        cashId: null,
      });
    }
    if (
      isSettled(b) &&
      b.settled_at &&
      (b.returned_cents ?? 0) + outlay(b) > 0
    ) {
      delta.set(`s:${b.id}`, (b.returned_cents ?? 0) - outlay(b));
      raw.push({
        id: `s:${b.id}`,
        at: b.settled_at,
        kind: "WAGER_PAYOUT",
        book: b.book,
        toBook: null,
        amount: b.returned_cents ?? 0,
        memo: `${b.status.toUpperCase()} · ${b.selection}`,
        cashId: null,
      });
    }
  }
  raw.sort(
    (a, b) =>
      a.at.localeCompare(b.at) ||
      RANK[a.kind] - RANK[b.kind] ||
      a.id.localeCompare(b.id),
  );
  let running = 0;
  return raw.map((r) => {
    running += delta.get(r.id) ?? 0;
    return { ...r, running };
  });
}

// ---- KPIs -------------------------------------------------------------------------------------

export interface Kpis {
  settled: number;
  pending: number;
  pendingExposure: number;
  pnl: number;
  staked: number;
  roi: number | null;
  wins: number;
  losses: number;
  pushes: number;
  clvMeasured: number;
  clvTotal: number;
  clvBeat: number | null;
  clvAvg: number | null;
  spark: number[];
}

function settledMs(b: TrackerBet) {
  return new Date(b.settled_at ?? b.placed_at).getTime();
}

export function kpis(
  bets: TrackerBet[],
  sinceMs: number | null = null,
  untilMs: number | null = null,
): Kpis {
  const inWindow = (b: TrackerBet) =>
    (sinceMs == null || settledMs(b) >= sinceMs) &&
    (untilMs == null || settledMs(b) < untilMs);
  const settled = bets
    .filter((b) => isSettled(b) && inWindow(b))
    .sort((a, b) => settledMs(a) - settledMs(b));
  const pending = bets.filter((b) => !isSettled(b));
  let pnl = 0;
  let staked = 0;
  let wins = 0;
  let losses = 0;
  let pushes = 0;
  const spark: number[] = [];
  for (const b of settled) {
    const p = profit(b) ?? 0;
    pnl += p;
    staked += outlay(b);
    spark.push(pnl);
    if (b.status === "won" || (b.status === "cashout" && p > 0)) wins++;
    else if (b.status === "lost" || (b.status === "cashout" && p < 0)) losses++;
    else pushes++;
  }
  const clvPool = bets.filter(
    (b) => b.clv != null && (isSettled(b) ? inWindow(b) : sinceMs == null),
  );
  const measured = clvPool
    .map((b) => (b.clv?.pct == null ? null : Number(b.clv.pct)))
    .filter((v): v is number => v != null && Number.isFinite(v));
  return {
    settled: settled.length,
    pending: pending.length,
    pendingExposure: pending.reduce((n, b) => n + outlay(b), 0),
    pnl,
    staked,
    roi: staked > 0 ? pnl / staked : null,
    wins,
    losses,
    pushes,
    clvMeasured: measured.length,
    clvTotal: bets.filter((b) => (isSettled(b) ? inWindow(b) : sinceMs == null))
      .length,
    clvBeat: measured.length
      ? measured.filter((v) => v > 0).length / measured.length
      : null,
    clvAvg: measured.length
      ? measured.reduce((n, v) => n + v, 0) / measured.length
      : null,
    spark,
  };
}

export function sparkPath(values: number[], w: number, h: number): string {
  if (values.length < 2) return "";
  const pts = [0, ...values];
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const span = hi - lo || 1;
  return pts
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${((i / (pts.length - 1)) * w).toFixed(1)},${(
          h -
          ((v - lo) / span) * (h - 4) -
          2
        ).toFixed(1)}`,
    )
    .join("");
}

// ---- history ----------------------------------------------------------------------------------

export interface DayPoint {
  day: string;
  bankroll: number;
  pnl: number;
  flows: number;
  evExpected: number;
  evPnl: number;
}

export function localDay(value: string | Date): string {
  const d = typeof value === "string" ? new Date(value) : value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// One point per calendar day from the first entry to today, replayed from the ledger, so the curve
// is complete even for days the app was never opened.
export function dailySeries(
  state: TrackerState,
  now: Date = new Date(),
): DayPoint[] {
  const events = new Map<
    string,
    { flows: number; pnl: number; evExpected: number; evPnl: number }
  >();
  const slot = (iso: string) => {
    const key = localDay(iso);
    let e = events.get(key);
    if (!e)
      events.set(key, (e = { flows: 0, pnl: 0, evExpected: 0, evPnl: 0 }));
    return e;
  };
  for (const c of state.cash) {
    if (c.kind === "transfer") continue;
    slot(c.occurred_at).flows +=
      c.kind === "withdrawal" ? -c.amount_cents : c.amount_cents;
  }
  for (const b of state.bets) {
    const p = profit(b);
    if (p == null || !b.settled_at) continue;
    const e = slot(b.settled_at);
    e.pnl += p;
    if (b.ev_ratio != null && b.stake_type === "cash" && b.status !== "void") {
      e.evExpected += b.stake_cents * Number(b.ev_ratio);
      e.evPnl += p;
    }
  }
  const keys = [...events.keys()].sort();
  if (!keys.length) return [];
  const out: DayPoint[] = [];
  let flows = 0;
  let pnl = 0;
  let evExpected = 0;
  let evPnl = 0;
  const end = localDay(now);
  const cursor = new Date(`${keys[0]}T12:00:00`);
  for (let guard = 0; guard < 4000; guard++) {
    const day = localDay(cursor);
    if (day > end && day > keys[keys.length - 1]) break;
    const e = events.get(day);
    if (e) {
      flows += e.flows;
      pnl += e.pnl;
      evExpected += e.evExpected;
      evPnl += e.evPnl;
    }
    out.push({ day, bankroll: flows + pnl, pnl, flows, evExpected, evPnl });
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
}

export interface Drawdown {
  maxCents: number;
  // Of the bankroll at the peak the drop started from; null when that bankroll was not positive.
  maxPct: number | null;
  currentCents: number;
  peakDay: string | null;
  troughDay: string | null;
}

// Peak-to-trough fall of cumulative realized profit (deposits and withdrawals never count as a drop).
export function drawdown(series: DayPoint[]): Drawdown {
  let peak = 0;
  let peakBank = series[0] ? series[0].bankroll - series[0].pnl : 0;
  let peakDay: string | null = null;
  let max = 0;
  let maxPct: number | null = null;
  let maxPeakDay: string | null = null;
  let maxTroughDay: string | null = null;
  for (const p of series) {
    if (p.pnl > peak) {
      peak = p.pnl;
      peakBank = p.bankroll;
      peakDay = p.day;
    }
    const down = peak - p.pnl;
    if (down > max) {
      max = down;
      maxPct = peakBank > 0 ? down / peakBank : null;
      maxPeakDay = peakDay;
      maxTroughDay = p.day;
    }
  }
  const last = series[series.length - 1];
  return {
    maxCents: max,
    maxPct,
    currentCents: last ? peak - last.pnl : 0,
    peakDay: maxPeakDay,
    troughDay: maxTroughDay,
  };
}

// ---- sizing -----------------------------------------------------------------------------------

// Fractional Kelly: (edge / (decimal odds - 1)) x bankroll x scalar, floored to the cent.
export function kellyCents(
  edge: number,
  decimalOdds: number,
  bankrollCents: number,
  scalar: number,
): number {
  const net = decimalOdds - 1;
  if (!(edge > 0) || !(net > 0) || !(bankrollCents > 0) || !(scalar > 0))
    return 0;
  return Math.floor((edge / net) * bankrollCents * scalar);
}

export const edgeFromProbability = (probability: number, decimalOdds: number) =>
  probability * decimalOdds - 1;

export function cashOf(rows: BookBalance[], book: string): number {
  return rows.find((r) => r.book === book)?.liquid ?? 0;
}

export function cashEntryLabel(c: CashEntry): string {
  return c.kind === "transfer"
    ? `${bookLabel(c.book)} → ${bookLabel(c.to_book ?? c.book)}`
    : bookLabel(c.book);
}
