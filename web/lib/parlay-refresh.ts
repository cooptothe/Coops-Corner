import { request, sharedPages } from "./api";
import { reloadTools, loadProps } from "./refresh-api";
import type { Capabilities, Quote } from "./contracts";
import type { ParlayLeg } from "./parlay";

// Reads retained odds only. It does not call The Odds API or spend provider credits.
export async function refreshParlay(legs: ParlayLeg[]) {
  const needMain = legs.some((leg) => leg.source === "ev");
  const needProps = legs.some((leg) => leg.source === "prop");
  let quotes: Quote[] = [];
  if (needMain) {
    await reloadTools();
    const caps = await request<Capabilities>("capabilities");
    quotes = await sharedPages<Quote>(
      "quotes",
      caps.meta.snapshot_id,
      new AbortController().signal,
      { limit: 1000, maxOffset: 100000 },
    );
  }
  const props = needProps ? ((await loadProps()).bets ?? []) : [];
  const missing: string[] = [];
  const changed: string[] = [];
  const updated = legs.map((leg) => {
    if (Date.parse(leg.startsAt) <= Date.now()) {
      missing.push(leg.key);
      return leg;
    }
    if (leg.source === "ev") {
      const q = quotes.find(
        (q) =>
          q.game_id === leg.eventId &&
          q.sportsbook_id === leg.book &&
          q.market_key === leg.ref.market_key &&
          q.side === leg.ref.side &&
          (q.point == null
            ? leg.ref.point == null
            : Number(q.point) === Number(leg.ref.point)) &&
          q.contract_id === leg.ref.contract_id,
      );
      if (!q) {
        missing.push(leg.key);
        return leg;
      }
      if (q.decimal_odds !== leg.odds) changed.push(leg.key);
      return {
        ...leg,
        odds: q.decimal_odds,
        links: q.links ?? null,
        sourceIds: q.source_ids,
        observedAt: q.observed_at,
      };
    }
    const b = props.find(
      (b) =>
        b.event_id === leg.eventId &&
        b.book === leg.book &&
        b.market_key === leg.ref.prop_market &&
        b.player === leg.ref.player &&
        b.side.toLowerCase() === leg.ref.side &&
        (b.point == null
          ? leg.ref.point == null
          : Number(b.point) === Number(leg.ref.point)),
    );
    if (!b) {
      missing.push(leg.key);
      return leg;
    }
    if (b.price !== leg.odds) changed.push(leg.key);
    return {
      ...leg,
      odds: b.price,
      links: b.links ?? null,
      sourceIds: b.source_ids,
      observedAt: b.observed_at ?? "",
    };
  });
  return { legs: updated, missing, changed };
}
