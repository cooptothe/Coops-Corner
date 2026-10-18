import test from "node:test";
import assert from "node:assert/strict";
import { MARKETS, selection } from "../../frontend/format.mjs";
test("all five event markets have readable shared feed labels", () => {
  for (const key of [
    "alternate_spreads",
    "alternate_totals",
    "btts",
    "draw_no_bet",
    "team_totals",
  ] as const)
    assert.ok(MARKETS[key] && !MARKETS[key].includes("_"));
});
test("alternate spreads retain the handicap sign and team totals name the team", () => {
  assert.equal(
    selection({
      selection_name: "Hawks",
      point: "2.5",
      market_key: "alternate_spreads",
    }),
    "Hawks +2.5",
  );
  assert.equal(
    selection({
      selection_name: "Hawks Over",
      point: "1.5",
      market_key: "team_totals",
    }),
    "Hawks Over 1.5",
  );
  assert.equal(
    selection({ selection_name: "Yes", point: null, market_key: "btts" }),
    "Yes",
  );
});
