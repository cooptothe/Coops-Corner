import { mulDecimal, americanToDecimal } from "../../frontend/format.mjs";
import { resolveLink, safeUrl, type QuoteLinks } from "./bet-links";
import type { RefValue } from "./tracker-api";

export const PARLAY_MAX = 8;
export function acceptedAmericanOdds(value: string): string {
  const odds = value.trim();
  if (!/^[+-]?\d{3,9}$/.test(odds))
    throw new Error("Enter accepted American odds, such as +325 or -150.");
  return americanToDecimal(
    odds.startsWith("+") || odds.startsWith("-") ? odds : `+${odds}`,
  );
}
export interface ParlayLeg {
  key: string;
  source: "ev" | "prop";
  eventId: string;
  book: string;
  matchup: string;
  selection: string;
  market: string;
  sportKey: string;
  startsAt: string;
  odds: string;
  observedAt: string;
  links: QuoteLinks | null;
  sourceIds?: { market?: string | null; outcome?: string | null } | null;
  ref: Record<string, RefValue>;
}
export interface ParlayDraft {
  id: string;
  book: string;
  stake: string;
  active: boolean;
  legs: ParlayLeg[];
}
export function legKey(leg: Omit<ParlayLeg, "key">) {
  const fixture = `${fixtureName(leg.matchup)}|${leg.startsAt}`;
  return [
    fixture,
    leg.book,
    leg.market,
    leg.ref.player ?? "",
    leg.ref.side ?? "",
    leg.ref.point ?? "",
  ].join("|");
}

export function fixtureName(matchup: string) {
  return matchup
    .trim()
    .toLowerCase()
    .replace(/\s+(?:@|at|vs\.?)\s+/g, " at ")
    .replace(/\s+/g, " ");
}

export interface BuilderBet {
  gameId: string;
  bookId: string;
  matchup: string;
  line: string;
  market: string;
  sportKey: string;
  startsAt: string;
  decimalOdds: string;
  observedAt: string | null;
  links?: QuoteLinks | null;
  sourceIds?: ParlayLeg["sourceIds"];
  lay?: boolean;
  ref?: Record<string, RefValue>;
}
export function builderLeg(bet: BuilderBet, source: "ev" | "prop"): ParlayLeg {
  const leg = {
    source,
    eventId: bet.gameId,
    book: bet.bookId,
    matchup: bet.matchup,
    selection: bet.line,
    market: bet.market,
    sportKey: bet.sportKey,
    startsAt: bet.startsAt,
    odds: bet.decimalOdds,
    observedAt: bet.observedAt ?? "",
    links: bet.links ?? null,
    sourceIds: bet.sourceIds,
    ref: { ...bet.ref, ...(bet.lay ? { lay: true } : {}) },
  };
  return { ...leg, key: legKey(leg) };
}
export function selectionProblem(
  draft: ParlayDraft,
  leg: ParlayLeg,
  now = Date.now(),
) {
  if (leg.book !== draft.book)
    return "Choose a bet from the selected sportsbook.";
  if (
    !Number.isFinite(Date.parse(leg.startsAt)) ||
    Date.parse(leg.startsAt) <= now
  )
    return "This game has already started or has no valid start time.";
  if (
    !/^\d+(\.\d{1,12})?$/.test(leg.odds) ||
    !(Number(leg.odds) > 1) ||
    !Number.isFinite(Number(leg.odds))
  )
    return "This price is unavailable.";
  if (draft.legs.some((l) => l.key === leg.key))
    return "This selection is already in your parlay.";
  if (draft.legs.length >= PARLAY_MAX)
    return "A parlay can contain up to eight legs.";
  if (
    draft.legs.some(
      (l) =>
        sameGame(l, leg) &&
        l.ref.market_key === leg.ref.market_key &&
        l.market === leg.market &&
        l.ref.player === leg.ref.player &&
        l.ref.prop_market === leg.ref.prop_market,
    )
  )
    return "Choose only one selection from this player/market in the same game.";
  if (leg.ref.lay === true) return "Lay bets cannot be added to a parlay.";
  return null;
}
export function sameGame(a: ParlayLeg, b: ParlayLeg) {
  return (
    (!!a.eventId && a.eventId === b.eventId) ||
    (fixtureName(a.matchup) === fixtureName(b.matchup) &&
      Date.parse(a.startsAt) === Date.parse(b.startsAt))
  );
}
export function hasSameGameLegs(legs: ParlayLeg[]) {
  return legs.some((leg, i) =>
    legs.slice(0, i).some((other) => sameGame(leg, other)),
  );
}
export function parlayKind(legs: ParlayLeg[]) {
  return !hasSameGameLegs(legs)
    ? "Cross-game parlay"
    : legs.every((leg) => sameGame(legs[0], leg))
      ? "Same-game parlay"
      : "Same-game parlay +";
}
export function combinedOdds(legs: ParlayLeg[]): string | null {
  if (hasSameGameLegs(legs)) return null;
  return legs.reduce((total, leg) => mulDecimal(total, leg.odds), "1");
}
export function readDraft(value: unknown): ParlayDraft | null {
  if (!value || typeof value !== "object") return null;
  const draft = value as ParlayDraft;
  if (
    typeof draft.id !== "string" ||
    typeof draft.book !== "string" ||
    typeof draft.stake !== "string" ||
    typeof draft.active !== "boolean" ||
    !Array.isArray(draft.legs) ||
    draft.legs.length > PARLAY_MAX
  )
    return null;
  const validated: ParlayDraft = { ...draft, legs: [] };
  for (const leg of draft.legs) {
    if (
      !leg ||
      !["ev", "prop"].includes(leg.source) ||
      ![
        leg.key,
        leg.eventId,
        leg.book,
        leg.market,
        leg.matchup,
        leg.selection,
        leg.sportKey,
        leg.startsAt,
        leg.odds,
        leg.observedAt,
      ].every((s) => typeof s === "string") ||
      !leg.ref ||
      typeof leg.ref !== "object"
    )
      return null;
    // Past legs are restored for review, but can never be handed off without checking.
    if (selectionProblem(validated, leg, 0)) return null;
    validated.legs.push(leg);
  }
  return validated;
}

// FanDuel's indexed market/selection format. No IDs or hostnames are invented.
// Every leg must have a provider-supplied FanDuel selection link, and the output is
// round-tripped below to verify that all pairs survived the complete-slip encoding.
export function parlayHandoff(
  legs: ParlayLeg[],
  state = "",
): { url: string | null; reason: string | null } {
  if (legs.length < 2) return { url: null, reason: "Add at least two legs." };
  if (new Set(legs.map((l) => l.book)).size !== 1)
    return { url: null, reason: "All legs must use the same sportsbook." };
  if (legs.some((l) => Date.parse(l.startsAt) <= Date.now()))
    return { url: null, reason: "Remove any games that have started." };
  if (hasSameGameLegs(legs))
    return {
      url: null,
      reason:
        "Build these selections in the sportsbook’s same-game parlay builder and use its combined quote. Copy the slip or open the individual selections below.",
    };
  if (legs[0].book !== "fanduel")
    return {
      url: null,
      reason:
        "Full-slip links are not available for this book yet. Copy the slip and use the individual leg links.",
    };
  let base: URL | null = null;
  const pairs: [string, string][] = [];
  for (const leg of legs) {
    const resolved = resolveLink({ outcome: leg.links?.outcome }, { state });
    if (!resolved.url || resolved.kind !== "betslip")
      return {
        url: null,
        reason:
          "A leg is missing its sportsbook selection link. Copy the slip instead.",
      };
    const url = new URL(resolved.url);
    if (
      !(
        url.hostname === "fanduel.com" || url.hostname.endsWith(".fanduel.com")
      ) ||
      !url.pathname.endsWith("/addToBetslip")
    )
      return {
        url: null,
        reason: "This selection link cannot load a complete FanDuel slip.",
      };
    const market = leg.sourceIds?.market ?? url.searchParams.get("marketId");
    const outcome =
      leg.sourceIds?.outcome ?? url.searchParams.get("selectionId");
    if (
      !market ||
      !outcome ||
      !/^[\d.]+$/.test(market) ||
      !/^\d+$/.test(outcome) ||
      url.searchParams.get("marketId") !== market ||
      url.searchParams.get("selectionId") !== outcome
    )
      return {
        url: null,
        reason: "A leg's native selection IDs are missing or inconsistent.",
      };
    if (base && (base.origin !== url.origin || base.pathname !== url.pathname))
      return {
        url: null,
        reason: "The selections use different sportsbook destinations.",
      };
    base ??= url;
    pairs.push([market, outcome]);
  }
  if (!base || new Set(pairs.map((p) => p.join("|"))).size !== pairs.length)
    return {
      url: null,
      reason: "Duplicate native selections are not allowed.",
    };
  base.search = "";
  pairs.forEach(([market, selection], i) => {
    base!.searchParams.set(`marketId[${i}]`, market);
    base!.searchParams.set(`selectionId[${i}]`, selection);
  });
  if (
    pairs.some(
      ([market, selection], i) =>
        base!.searchParams.get(`marketId[${i}]`) !== market ||
        base!.searchParams.get(`selectionId[${i}]`) !== selection,
    )
  )
    return {
      url: null,
      reason: "The complete-slip encoding failed verification.",
    };
  const safe = safeUrl(base.toString());
  return {
    url: safe,
    reason: safe
      ? null
      : "The combined slip link is too long. Copy the slip instead.",
  };
}
