import { notifyUnauthorized } from "./auth-api";

export type Strategy =
  "ev" | "arbitrage" | "middle" | "promo" | "prop" | "manual";
export type BetStatus =
  "pending" | "won" | "lost" | "push" | "void" | "cashout";
export type Result = Exclude<BetStatus, "pending">;
export type CashKind = "deposit" | "withdrawal" | "transfer" | "adjustment";
// bonus: free stake, a win pays winnings only. credit: free stake, a win pays winnings plus the credit.
export type StakeType = "cash" | "bonus" | "credit";
export type RefValue = string | number | boolean | null;

export interface Clv {
  // Closing value of the price we took: decimal odds times closing fair probability, minus one.
  pct: string | null;
  close_odds?: string;
  fair_prob?: string;
  books?: string[];
  reason?: string;
  at: string;
}

export interface TrackerBet {
  id: string;
  client_key: string;
  group_id: string | null;
  created_at: string;
  placed_at: string;
  strategy: Strategy;
  sport_key: string;
  matchup: string;
  starts_at: string | null;
  market: string;
  selection: string;
  book: string;
  // Decimal odds as a string (the ledger is decimal-only).
  odds: string;
  stake_cents: number;
  stake_type: StakeType;
  status: BetStatus;
  returned_cents: number | null;
  settled_at: string | null;
  fair_prob: string | null;
  ev_ratio: string | null;
  ref: Record<string, RefValue>;
  clv: Clv | null;
  notes: string;
}

export interface CashEntry {
  id: string;
  client_key: string;
  occurred_at: string;
  kind: CashKind;
  amount_cents: number;
  book: string;
  to_book: string | null;
  note: string;
}

export interface TrackerState {
  bets: TrackerBet[];
  cash: CashEntry[];
}

export interface LiveView {
  state: "pre" | "in" | "post" | "unknown";
  detail: string;
  score: { away?: number | null; home?: number | null };
  progress: { value: number; line: number; side: string } | null;
  suggest: { result: "won" | "lost" | "push"; basis: string } | null;
}

export interface NewBetBody {
  client_key: string;
  strategy: Strategy;
  matchup: string;
  selection: string;
  book: string;
  odds: string;
  stake: string;
  sport_key?: string;
  starts_at?: string | null;
  market?: string;
  stake_type?: StakeType;
  group_id?: string | null;
  fair_prob?: string | null;
  ev_ratio?: string | null;
  placed_at?: string;
  notes?: string;
  ref?: Record<string, RefValue>;
}

export interface NewCashBody {
  client_key: string;
  kind: CashKind;
  amount: string;
  book: string;
  to_book?: string;
  occurred_at?: string;
  note?: string;
}

export class TrackerRequestError extends Error {}

const BASE = "/api/refresh/v1/tracker";

async function call<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      cache: "no-store",
      ...(body !== undefined && {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      signal: AbortSignal.any([
        ...(signal ? [signal] : []),
        AbortSignal.timeout(method === "GET" ? 30000 : 15000),
      ]),
    });
  } catch {
    throw new TrackerRequestError(
      "The tracker service is not reachable. Start it with: python -m pipelines.refresh_service",
    );
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401) notifyUnauthorized();
  if (!response.ok)
    throw new TrackerRequestError(
      (data && typeof data.error === "string" && data.error) ||
        "The tracker could not complete that request.",
    );
  return data as T;
}

export const loadTracker = (signal?: AbortSignal) =>
  call<TrackerState>("GET", "/state", undefined, signal);
export const loadLive = (signal?: AbortSignal) =>
  call<{ live: Record<string, LiveView> }>("GET", "/live", undefined, signal);
// Measures closing-line value for bets whose games have started; the server skips everything else.
export const measureClv = () =>
  call<{ bets: TrackerBet[] }>("POST", "/clv", {});
export const addBets = (bets: NewBetBody[]) =>
  call<{ bets: TrackerBet[] }>("POST", "/bets", bets);
export const updateBet = (id: string, changes: Record<string, unknown>) =>
  call<{ bet: TrackerBet }>("PATCH", `/bets/${id}`, changes);
export const settleBet = (
  id: string,
  result: Result,
  extra?: { returned?: string; settled_at?: string },
) =>
  call<{ bet: TrackerBet }>("POST", `/bets/${id}/settle`, { result, ...extra });
export const reopenBet = (id: string) =>
  call<{ bet: TrackerBet }>("POST", `/bets/${id}/reopen`, {});
export const deleteBet = (id: string) =>
  call<{ ok: true }>("DELETE", `/bets/${id}`);
export const addCash = (entry: NewCashBody) =>
  call<{ cash: CashEntry }>("POST", "/cash", entry);
export const deleteCash = (id: string) =>
  call<{ ok: true }>("DELETE", `/cash/${id}`);
