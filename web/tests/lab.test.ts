import assert from "node:assert/strict";
import { test } from "node:test";
import { labHref, labDate, labLeg } from "../lib/lab";
import type { TrendContract } from "../lib/trends-api";
const contract: TrendContract = {
  id: "raw-1",
  bet_id: "bet",
  event_id: "event",
  player: "Player",
  sport_key: "basketball_nba",
  market_key: "player_points",
  home: "Home",
  away: "Away",
  side: "Over",
  point: "20.5",
  price: "2.10",
  book: "fanduel",
  starts_at: "2030-01-01T12:00:00Z",
  observed_at: "2029-12-31T22:00:00Z",
};
test("Lab links encode selections and dates use Central time", () => {
  assert.equal(labHref(), "/lab");
  assert.equal(
    new URL(
      labHref("a&next=https://example.com"),
      "https://coopscorner.tech",
    ).searchParams.get("bet"),
    "a&next=https://example.com",
  );
  assert.equal(labDate("invalid"), "Date unavailable");
  assert.equal(labDate("2026-10-17T01:00:00Z", true), "Oct 16");
});
test("Lab parlay legs bind exact retained contracts without inventing probabilities", () => {
  const leg = labLeg(contract)!;
  assert.equal(leg.source, "prop");
  assert.equal(leg.odds, "2.10");
  assert.equal(leg.ref.lab_contract_id, "raw-1");
  assert.equal(leg.eventId, "event");
  assert.equal(labLeg({ ...contract, event_id: "" }), null);
  assert.equal(labLeg({ ...contract, side: "Yes" }), null);
  assert.equal(labLeg({ ...contract, observed_at: undefined }), null);
  assert.equal(labLeg({ ...contract, point: "" }), null);
});

test("Lab scorer legs preserve the real no-line Yes contract", () => {
  const scorer = {
    ...contract,
    side: "Yes",
    point: "0.5",
    settlement_point: null,
    market_key: "player_goal_scorer_anytime",
  };
  const leg = labLeg(scorer)!;
  assert.equal(leg.ref.point, null);
  assert.equal(leg.ref.side, "yes");
  assert.equal(leg.ref.prop_market, "player_goal_scorer_anytime");
});
