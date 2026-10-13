// Which feed bets the account has already tracked, so a bet is not placed twice. Pure matching only.
import type { RefValue, TrackerBet } from "./tracker-api";
import { bookCode } from "./tracker-math";

type Ref = Record<string, RefValue> | undefined;
const text = (v: RefValue | undefined) =>
  typeof v === "string" && v ? v.trim().toLowerCase() : null;

// The identity of one bet at one sportsbook: the same game, market, line and side. Odds and stake are not part of
// it (a price moving does not make it a different bet). Bets without a recorded reference (manual ones) have none.
export function betKey(ref: Ref, book: string): string | null {
  if (!ref) return null;
  const game = text(ref.game_id);
  const side = text(ref.side);
  if (!game || !side || !book) return null;
  const point = typeof ref.point === "number" ? String(ref.point) : "";
  if (ref.market_key === "prop") {
    const market = text(ref.prop_market);
    const player = text(ref.player);
    return market && player
      ? `p|${game}|${market}|${player}|${side}|${point}|${book}`
      : null;
  }
  const contract = text(ref.contract_id);
  const market = text(ref.market_key);
  return contract && market
    ? `f|${game}|${contract}|${market}|${side}|${book}`
    : null;
}

export interface PlacedBet {
  parlayCount?: number;
  count: number;
  stakeCents: number;
}
export type PlacedIndex = Map<string, PlacedBet>;

// Open bets only: a settled, voided or cashed-out bet no longer stands in the way of betting again.
export function placedIndex(bets: TrackerBet[]): PlacedIndex {
  const index: PlacedIndex = new Map();
  for (const bet of bets) {
    if (bet.status !== "pending") continue;
    for (const ref of bet.legs?.length
      ? bet.legs.map((leg) => leg.ref)
      : [bet.ref]) {
      const key = betKey(ref, bet.book);
      if (!key) continue;
      const seen = index.get(key) ?? { count: 0, stakeCents: 0 };
      const parlays = (seen.parlayCount ?? 0) + (bet.legs?.length ? 1 : 0);
      index.set(key, {
        count: seen.count + 1,
        stakeCents: seen.stakeCents + (bet.legs?.length ? 0 : bet.stake_cents),
        ...(parlays ? { parlayCount: parlays } : {}),
      });
    }
  }
  return index;
}

export interface PlacedLeg {
  ref?: Ref;
  // The sportsbook as the feed labels it ("FanDuel").
  bookLabel: string;
}
export interface PlacedState {
  parlayLegs?: number;
  legs: number;
  placed: number;
  stakeCents: number;
}
export const NOT_PLACED: PlacedState = { legs: 0, placed: 0, stakeCents: 0 };

export function placedState(
  index: PlacedIndex,
  legs: PlacedLeg[],
): PlacedState {
  let placed = 0;
  let stakeCents = 0;
  let parlayLegs = 0;
  for (const leg of legs) {
    const key = betKey(leg.ref, bookCode(leg.bookLabel));
    const hit = key ? index.get(key) : undefined;
    if (hit) {
      placed++;
      stakeCents += hit.stakeCents;
      if (hit.parlayCount) parlayLegs++;
    }
  }
  return {
    legs: legs.length,
    placed,
    stakeCents,
    ...(parlayLegs ? { parlayLegs } : {}),
  };
}
