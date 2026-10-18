import { test } from "node:test";
import assert from "node:assert/strict";
import {
  restoredFetchMarkets,
  withAlternateMarkets,
} from "../lib/props-fetch-settings";
import { savedTimeFilter } from "../lib/feed-time";

const catalog = [
  { key: "points", default: true },
  { key: "assists", default: false },
];
test("restoring custom or empty fetch choices does not replace them with defaults", () => {
  assert.deepEqual(restoredFetchMarkets(["assists"], catalog), ["assists"]);
  assert.deepEqual(restoredFetchMarkets([], catalog), []);
  assert.deepEqual(restoredFetchMarkets(["removed", "assists"], catalog), [
    "assists",
  ]);
});
test("default settings restore default markets and safely validate the time filter", () => {
  assert.deepEqual(restoredFetchMarkets(null, catalog), ["points"]);
  assert.equal(savedTimeFilter("3d"), "3d");
  assert.equal(savedTimeFilter("bad"), "default");
});

test("adding alternate lines preserves choices, excludes unsupported keys and is idempotent", () => {
  const markets = [
    { key: "player_points" },
    { key: "player_points_alternate" },
    { key: "player_anytime_td" },
  ];
  const original = ["player_points", "player_anytime_td"];
  const result = withAlternateMarkets(original, markets);
  assert.deepEqual(result, [...original, "player_points_alternate"]);
  assert.deepEqual(withAlternateMarkets(result, markets), result);
  assert.deepEqual(withAlternateMarkets([], markets), []);
  assert.deepEqual(original, ["player_points", "player_anytime_td"]);
});
