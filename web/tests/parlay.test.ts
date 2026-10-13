import assert from "node:assert/strict";
import { test } from "node:test";
import {
  combinedOdds,
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
