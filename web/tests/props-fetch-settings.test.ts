import { test } from "node:test";
import assert from "node:assert/strict";
import { restoredFetchMarkets } from "../lib/props-fetch-settings";
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
