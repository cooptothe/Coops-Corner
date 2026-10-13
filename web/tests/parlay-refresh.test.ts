import assert from "node:assert/strict";
import { test } from "node:test";
import { refreshParlay } from "../lib/parlay-refresh";
import type { ParlayLeg } from "../lib/parlay";

const future = new Date(Date.now() + 86400000).toISOString();
const main: ParlayLeg = {
  key: "main",
  source: "ev",
  eventId: "e1",
  book: "fanduel",
  matchup: "A at B",
  market: "Moneyline",
  selection: "Home",
  sportKey: "basketball_nba",
  startsAt: future,
  odds: "2",
  observedAt: future,
  links: null,
  ref: { market_key: "h2h", contract_id: "c1", side: "home", point: null },
};
const prop: ParlayLeg = {
  ...main,
  key: "prop",
  source: "prop",
  eventId: "e2",
  matchup: "C at D",
  ref: {
    prop_market: "player_points",
    player: "Player",
    side: "over",
    point: 20.5,
  },
};
test("review uses stored data, updates changed odds and detects missing selections across both feeds", async () => {
  const original = globalThis.fetch;
  const paths: string[] = [];
  const meta = {
    format: "corner.product_api/1",
    data_mode: "fixture",
    snapshot_id: "parlay-review-test-1",
    production_authorized: false,
    availability_verified: false,
  };
  globalThis.fetch = async (input) => {
    const path = String(input);
    paths.push(path);
    if (path.includes("/catalog/reload")) return Response.json({ ok: true });
    if (path.includes("/capabilities"))
      return Response.json({ meta, data: {} });
    if (path.includes("/quotes"))
      return Response.json({
        meta,
        data: {
          items: [
            {
              game_id: "e1",
              sportsbook_id: "fanduel",
              market_key: "h2h",
              contract_id: "c1",
              side: "home",
              point: null,
              decimal_odds: "2.2",
              links: {
                outcome:
                  "https://sportsbook.fanduel.com/addToBetslip?marketId=42.1&selectionId=1",
              },
              observed_at: future,
            },
          ],
          total: 1,
          next_offset: null,
          limit: 1000,
          offset: 0,
        },
      });
    if (path.includes("/props")) return Response.json({ bets: [] });
    throw new Error(`Unexpected request: ${path}`);
  };
  try {
    const result = await refreshParlay([main, prop]);
    assert.deepEqual(result.changed, ["main"]);
    assert.deepEqual(result.missing, ["prop"]);
    assert.equal(result.legs[0].odds, "2.2");
    assert.ok(
      paths.every(
        (path) => !path.includes("the-odds-api") && !path.includes("/odds"),
      ),
    );
  } finally {
    globalThis.fetch = original;
  }
});
