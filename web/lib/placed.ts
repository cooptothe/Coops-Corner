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
type ExposureKind = "player" | "team" | "event";
export interface RelatedExposure {
  level: "market" | "entity";
  kind: ExposureKind;
}
export type PlacedIndex = Map<string, PlacedBet> & {
  markets?: Set<string>;
  entities?: Set<string>;
};

// Market exposure ignores sportsbook, line and direction. Entity exposure stays
// within this event; a similarly named player in another game is not a match.
function exposureKeys(
  ref: Ref,
): { market: string; entity: string; kind: ExposureKind } | null {
  if (!ref) return null;
  const game = text(ref.game_id),
    side = text(ref.side),
    market = text(ref.market_key);
  if (!game || !side || !market) return null;
  if (market === "prop") {
    const player = text(ref.player)?.replace(/\s+/g, " "),
      prop = text(ref.prop_market);
    return player && prop
      ? {
          market: JSON.stringify([game, player, prop]),
          entity: JSON.stringify(["player", game, player]),
          kind: "player",
        }
      : null;
  }
  if (!text(ref.contract_id)) return null;
  const kind = side === "home" || side === "away" ? "team" : "event";
  return {
    market: JSON.stringify([game, market.replace(/_lay$/, "")]),
    entity: JSON.stringify([kind, game, kind === "team" ? side : "event"]),
    kind,
  };
}

// Open bets only: a settled, voided or cashed-out bet no longer stands in the way of betting again.
export function placedIndex(bets: TrackerBet[]): PlacedIndex {
  const index: PlacedIndex = new Map();
  index.markets = new Set();
  index.entities = new Set();
  for (const bet of bets) {
    if (bet.status !== "pending") continue;
    for (const leg of bet.legs?.length
      ? bet.legs.filter((leg) => !leg.status || leg.status === "pending")
      : [{ ref: bet.ref, book: bet.book }]) {
      const ref = leg.ref;
      const key = betKey(ref, leg.book || bet.book);
      if (!key) continue;
      const exposure = exposureKeys(ref);
      if (exposure) {
        index.markets.add(exposure.market);
        index.entities.add(exposure.entity);
      }
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
  related?: RelatedExposure;
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
  let related: RelatedExposure | undefined;
  for (const leg of legs) {
    const key = betKey(leg.ref, bookCode(leg.bookLabel));
    const hit = key ? index.get(key) : undefined;
    const exposure = exposureKeys(leg.ref);
    if (exposure && index.markets?.has(exposure.market))
      related = { level: "market", kind: exposure.kind };
    else if (!related && exposure && index.entities?.has(exposure.entity))
      related = { level: "entity", kind: exposure.kind };
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
    ...(!placed && related ? { related } : {}),
  };
}
