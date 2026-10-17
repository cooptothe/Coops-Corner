import assert from "node:assert/strict";
import { test } from "node:test";
import {
  combinedOdds,
  hasSameGameLegs,
  parlayKind,
  acceptedAmericanOdds,
  readDraft,
  selectionProblem,
  parlayHandoff,
  type ParlayLeg,
  type ParlayDraft,
} from "../lib/parlay";
import { bookBalances, totals } from "../lib/tracker-math";
import type { TrackerBet } from "../lib/tracker-api";

const future = new Date(Date.now() + 3600000).toISOString();
function leg(i: number, source: "ev" | "prop" = "ev"): ParlayLeg {
  return {
    key: `l${i}`,
    source,
    eventId: `e${i}`,
    book: "fanduel",
    matchup: `A${i} at B${i}`,
    market: "h2h",
    selection: "Home",
    sportKey: "basketball_nba",
    startsAt: future,
    odds: "2.1",
    observedAt: new Date().toISOString(),
    ref: { side: "home", point: null },
    sourceIds: { market: `42.${i}`, outcome: `${100 + i}` },
    links: {
      outcome: `https://sportsbook.fanduel.com/addToBetslip?marketId=42.${i}&selectionId=${100 + i}`,
    },
  };
}
const draft: ParlayDraft = {
  id: "id",
  book: "fanduel",
  stake: "25",
  active: true,
  legs: [leg(1)],
};
test("same-game and mixed-game drafts restore without fabricated combined prices", () => {
  const prop = {
    ...leg(2, "prop"),
    eventId: "e1",
    matchup: leg(1).matchup,
    market: "Points",
    ref: {
      market_key: "prop",
      prop_market: "player_points",
      player: "Player",
      side: "over",
      point: 20.5,
    },
  };
  assert.equal(selectionProblem(draft, prop), null);
  const sgp = { ...draft, legs: [leg(1), prop] };
  assert.deepEqual(readDraft(JSON.parse(JSON.stringify(sgp))), sgp);
  assert.equal(hasSameGameLegs(sgp.legs), true);
  assert.equal(parlayKind(sgp.legs), "Same-game parlay");
  assert.equal(parlayKind([...sgp.legs, leg(3)]), "Same-game parlay +");
  assert.equal(combinedOdds(sgp.legs), null);
  assert.equal(combinedOdds([...sgp.legs, leg(3)]), null);
  assert.equal(parlayHandoff(sgp.legs).url, null);
  assert.match(parlayHandoff(sgp.legs).reason!, /combined quote/);
  assert.ok(
    selectionProblem(sgp, {
      ...prop,
      key: "opposite",
      ref: { ...prop.ref, side: "under" },
    }),
  );
  assert.ok(
    selectionProblem(sgp, {
      ...prop,
      key: "alternate",
      ref: { ...prop.ref, point: 25.5 },
    }),
  );
});
test("mixed-source draft restores exactly and selection blocks incompatible legs", () => {
  const mixed = { ...draft, legs: [leg(1), leg(2, "prop")] };
  assert.deepEqual(readDraft(JSON.parse(JSON.stringify(mixed))), mixed);
  assert.ok(selectionProblem(draft, { ...leg(2), book: "draftkings" }));
  assert.ok(selectionProblem(draft, leg(1)));
  assert.ok(selectionProblem(draft, { ...leg(2), matchup: leg(1).matchup }));
  assert.ok(
    selectionProblem(draft, { ...leg(2), startsAt: new Date(0).toISOString() }),
  );
  assert.equal(selectionProblem(draft, leg(2, "prop")), null);
  assert.ok(selectionProblem(draft, { ...leg(2, "prop"), matchup: "A1 @ B1" }));
  assert.equal(combinedOdds(mixed.legs), "4.41");
});
test("complete FanDuel URL contains every native market/selection pair", () => {
  const result = parlayHandoff([leg(1), leg(2, "prop")]);
  assert.ok(result.url);
  const url = new URL(result.url);
  assert.equal(url.searchParams.get("marketId[0]"), "42.1");
  assert.equal(url.searchParams.get("selectionId[1]"), "102");
  assert.equal(url.searchParams.size, 4);
});
test("missing, mismatched, foreign-host, duplicate and unsupported links never masquerade as complete slips", () => {
  for (const bad of [
    { ...leg(2), links: null },
    { ...leg(2), sourceIds: { market: "wrong", outcome: "102" } },
    {
      ...leg(2),
      links: {
        outcome:
          "https://evil.example/addToBetslip?marketId=42.2&selectionId=102",
      },
    },
    { ...leg(2), sourceIds: leg(1).sourceIds, links: leg(1).links },
  ])
    assert.equal(parlayHandoff([leg(1), bad]).url, null);
  assert.equal(
    parlayHandoff([
      { ...leg(1), book: "pinnacle" },
      { ...leg(2), book: "pinnacle" },
    ]).url,
    null,
  );
});
test("parlay children never multiply bankroll stake or winnings", () => {
  const parent = {
    id: "p",
    book: "fanduel",
    stake_cents: 2500,
    odds: "4",
    status: "won",
    returned_cents: 10000,
    stake_type: "cash",
    legs: [leg(1), leg(2)],
  } as unknown as TrackerBet;
  const sum = totals(bookBalances({ bets: [parent], cash: [] }));
  assert.equal(sum.bankroll, 7500);
});

test("manual parlay tracking accepts American odds and preserves decimal storage", () => {
  assert.equal(acceptedAmericanOdds("+325"), "4.25");
  assert.equal(acceptedAmericanOdds("325"), "4.25");
  assert.equal(acceptedAmericanOdds(" -150 "), "1.666666666667");
  assert.equal(acceptedAmericanOdds("+100"), "2");
  for (const value of ["4.25", "99", "-99", "", "NaN", "1e3", "+100.5"])
    assert.throws(() => acceptedAmericanOdds(value));
});
