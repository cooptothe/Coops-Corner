// The tracker's single-store reducer. Live pushes replace only the entries that changed, so memoized
// rows whose bet and live view are untouched skip rendering entirely.
import type {
  BetStatus,
  CashEntry,
  LiveView,
  Strategy,
  TrackerBet,
} from "./tracker-api";
import { leagueLabel } from "./tracker-math";

export interface Filters {
  books: string[];
  leagues: string[];
  status: "all" | "active" | "settled" | BetStatus;
  strategy: "all" | Strategy;
  query: string;
}

export interface TrackerView {
  bets: TrackerBet[];
  cash: CashEntry[];
  live: Record<string, LiveView>;
  filters: Filters;
}

export type Action =
  | { type: "LOAD"; bets: TrackerBet[]; cash: CashEntry[] }
  | { type: "BET_UPSERT"; bets: TrackerBet[] }
  | { type: "BET_REMOVE"; id: string }
  | { type: "CASH_UPSERT"; cash: CashEntry }
  | { type: "CASH_REMOVE"; id: string }
  | { type: "LIVE_UPDATE"; live: Record<string, LiveView> }
  | { type: "SET_FILTER"; filters: Partial<Filters> };

export const EMPTY_FILTERS: Filters = {
  books: [],
  leagues: [],
  status: "all",
  strategy: "all",
  query: "",
};

export const initialView: TrackerView = {
  bets: [],
  cash: [],
  live: {},
  filters: EMPTY_FILTERS,
};

const byPlaced = (a: TrackerBet, b: TrackerBet) =>
  a.placed_at.localeCompare(b.placed_at) ||
  a.created_at.localeCompare(b.created_at);

// Keeps the previous object when the server's copy is identical, preserving identity for React.memo.
function keepIdentity<T>(prev: T | undefined, next: T): T {
  return prev !== undefined && JSON.stringify(prev) === JSON.stringify(next)
    ? prev
    : next;
}

export function trackerReducer(
  state: TrackerView,
  action: Action,
): TrackerView {
  switch (action.type) {
    case "LOAD": {
      const known = new Map(state.bets.map((b) => [b.id, b]));
      return {
        ...state,
        bets: action.bets.map((b) => keepIdentity(known.get(b.id), b)),
        cash: action.cash,
      };
    }
    case "BET_UPSERT": {
      const incoming = new Map(action.bets.map((b) => [b.id, b]));
      const merged = state.bets.map((b) =>
        incoming.has(b.id) ? keepIdentity(b, incoming.get(b.id)!) : b,
      );
      const have = new Set(state.bets.map((b) => b.id));
      return {
        ...state,
        bets: [...merged, ...action.bets.filter((b) => !have.has(b.id))].sort(
          byPlaced,
        ),
      };
    }
    case "BET_REMOVE": {
      const { [action.id]: _gone, ...live } = state.live;
      return {
        ...state,
        bets: state.bets.filter((b) => b.id !== action.id),
        live,
      };
    }
    case "CASH_UPSERT":
      return {
        ...state,
        cash: [
          ...state.cash.filter((c) => c.id !== action.cash.id),
          action.cash,
        ].sort(
          (a, b) =>
            a.occurred_at.localeCompare(b.occurred_at) ||
            a.id.localeCompare(b.id),
        ),
      };
    case "CASH_REMOVE":
      return { ...state, cash: state.cash.filter((c) => c.id !== action.id) };
    case "LIVE_UPDATE": {
      let changed =
        Object.keys(state.live).length !== Object.keys(action.live).length;
      const live: Record<string, LiveView> = {};
      for (const [id, view] of Object.entries(action.live)) {
        live[id] = keepIdentity(state.live[id], view);
        if (live[id] !== state.live[id]) changed = true;
      }
      return changed ? { ...state, live } : state;
    }
    case "SET_FILTER":
      return { ...state, filters: { ...state.filters, ...action.filters } };
  }
}

export function matchesFilters(bet: TrackerBet, f: Filters): boolean {
  if (f.books.length && !f.books.includes(bet.book)) return false;
  if (
    f.leagues.length &&
    ![bet.sport_key, ...(bet.legs ?? []).map((leg) => leg.sport_key)].some(
      (sport) => f.leagues.includes(sport),
    )
  )
    return false;
  if (f.strategy !== "all" && bet.strategy !== f.strategy) return false;
  if (f.status === "active" && bet.status !== "pending") return false;
  if (f.status === "settled" && bet.status === "pending") return false;
  if (
    f.status !== "all" &&
    f.status !== "active" &&
    f.status !== "settled" &&
    bet.status !== f.status
  )
    return false;
  const q = f.query.trim().toLowerCase();
  if (q) {
    const hay =
      `${bet.selection} ${bet.matchup} ${bet.market} ${bet.book} ${leagueLabel(bet.sport_key)} ${bet.notes} ${(bet.legs ?? []).map((leg) => `${leg.selection} ${leg.matchup} ${leg.market} ${leagueLabel(leg.sport_key)}`).join(" ")}`.toLowerCase();
    if (!q.split(/\s+/).every((word) => hay.includes(word))) return false;
  }
  return true;
}

// Pending bets lead (soonest game first); settled bets follow, newest first.
export function orderBets(bets: TrackerBet[]): TrackerBet[] {
  const time = (b: TrackerBet) => b.starts_at ?? b.placed_at;
  const pending = bets
    .filter((b) => b.status === "pending")
    .sort((a, b) => time(a).localeCompare(time(b)));
  const done = bets
    .filter((b) => b.status !== "pending")
    .sort((a, b) =>
      (b.settled_at ?? b.placed_at).localeCompare(a.settled_at ?? a.placed_at),
    );
  return [...pending, ...done];
}

export const filtersActive = (f: Filters) =>
  f.books.length > 0 ||
  f.leagues.length > 0 ||
  f.status !== "all" ||
  f.strategy !== "all" ||
  f.query.trim() !== "";
