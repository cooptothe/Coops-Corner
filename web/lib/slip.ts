// Every tool's "One-click bet" records into the local tracker ledger. Nothing here places a wager.
import { americanToDecimal } from "../../frontend/format.mjs";
import {
  addBets,
  type NewBetBody,
  type RefValue,
  type StakeType,
  type Strategy,
  type TrackerBet,
} from "./tracker-api";
import { bookCode } from "./tracker-math";
import { splitMatchup } from "./media";

// Before the tracker existed, bets were kept in this browser key. It is imported once, then removed.
export const LEGACY_SLIP_KEY = "corner.slip";

export interface NewBet {
  matchup: string;
  // The selection as shown ("Jayson Tatum · Over 5.5").
  line: string;
  // Sportsbook label ("FanDuel"); mapped to the ledger's book code.
  book: string;
  // American odds as shown on the slip, e.g. "+110".
  odds: string;
  // Dollars with up to two decimals.
  stake: string;
  strategy?: Strategy;
  sportKey?: string;
  startsAt?: string;
  market?: string;
  stakeType?: StakeType;
  // Overrides the conversion of `odds`: boosted, or lay-equivalent prices have no American form here.
  decimalOdds?: string;
  fairProb?: string;
  evRatio?: string;
  groupId?: string;
  notes?: string;
  ref?: Record<string, RefValue>;
}

export const MIN_STAKE = /^\d{1,9}(\.\d{1,2})?$/;

// The identifying facts of a quote, used later to look up live results and the closing line.
export function quoteRef(
  q: {
    game_id: string;
    contract_id: string;
    market_key: string;
    side: string;
    point: string | null;
  },
  extra: Record<string, RefValue> = {},
): Record<string, RefValue> {
  const point = q.point == null ? null : Number(q.point);
  return {
    game_id: q.game_id,
    contract_id: q.contract_id,
    market_key: q.market_key,
    side: q.side,
    point: point != null && Number.isFinite(point) ? point : null,
    ...extra,
  };
}

function body(bet: NewBet, key: string, groupId: string): NewBetBody {
  const sides = splitMatchup(bet.matchup);
  const ref: Record<string, RefValue> = { ...bet.ref };
  if (sides) {
    ref.away ??= sides[0];
    ref.home ??= sides[1];
  }
  for (const k of Object.keys(ref)) if (ref[k] == null) delete ref[k];
  return {
    client_key: key,
    strategy: bet.strategy ?? "manual",
    matchup: sides ? `${sides[0]} at ${sides[1]}` : bet.matchup,
    selection: bet.line,
    book: bookCode(bet.book),
    odds: bet.decimalOdds ?? americanToDecimal(bet.odds),
    stake: bet.stake,
    sport_key: bet.sportKey ?? "",
    starts_at: bet.startsAt || null,
    market: bet.market ?? "",
    stake_type: bet.stakeType ?? "cash",
    group_id: bet.groupId ?? groupId,
    fair_prob: bet.fairProb ?? null,
    ev_ratio: bet.evRatio ?? null,
    notes: bet.notes ?? "",
    ref,
  };
}

// Legs of one play are saved together, atomically. `attempt` makes a retry after a network failure
// idempotent: the same attempt can never record the same leg twice.
export async function logBets(
  bets: NewBet[],
  attempt: string = crypto.randomUUID(),
): Promise<TrackerBet[]> {
  const group = bets.length > 1 ? `g:${attempt}` : "";
  const saved = await addBets(
    bets.map((bet, i) => body(bet, `ui:${attempt}:${i}`, group)),
  );
  notifyLogged();
  return saved.bets;
}

const EVENT = "corner:bet-logged";
export const notifyLogged = () => window.dispatchEvent(new Event(EVENT));
export function onLogged(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

interface LegacyBet {
  at: string;
  matchup: string;
  line: string;
  book: string;
  odds: string;
  stake: string;
}

let importing: Promise<number> | null = null;

// Moves the old browser-only log into the ledger as pending manual bets. The browser copy is removed
// only after the ledger confirms it holds them, so a failure loses nothing.
export function importLegacySlip(): Promise<number> {
  importing ??= (async () => {
    let raw: LegacyBet[] = [];
    try {
      const parsed = JSON.parse(localStorage.getItem(LEGACY_SLIP_KEY) ?? "[]");
      raw = Array.isArray(parsed) ? parsed : [];
    } catch {
      return 0;
    }
    if (!raw.length) return 0;
    const items: NewBetBody[] = [];
    for (const b of raw) {
      try {
        if (!MIN_STAKE.test(String(b.stake))) continue;
        items.push({
          client_key: `slip:${b.at}`,
          strategy: "manual",
          matchup: String(b.matchup),
          selection: String(b.line),
          book: bookCode(String(b.book)),
          odds: americanToDecimal(String(b.odds)),
          stake: String(b.stake),
          placed_at: b.at,
          notes: "Imported from the old browser log",
        });
      } catch {
        // An unreadable old entry is skipped rather than blocking the rest.
      }
    }
    try {
      for (let i = 0; i < items.length; i += 12)
        await addBets(items.slice(i, i + 12));
      localStorage.removeItem(LEGACY_SLIP_KEY);
      return items.length;
    } catch {
      importing = null;
      return 0;
    }
  })();
  return importing;
}
