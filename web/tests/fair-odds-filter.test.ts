import test from "node:test";
import assert from "node:assert/strict";
import { fairOddsRange } from "../lib/fair-odds-filter";
test("fair odds, rather than offered sportsbook odds, determine range membership", () => {
  const range = fairOddsRange("-200", "+100");
  assert.equal(range.test("0.6"), true); // fair -150, regardless of an offered +200 price
  assert.equal(range.test("0.4"), false); // fair +150, regardless of an offered -110 price
});
test("exact inclusive probability boundaries and signed American odds", () => {
  assert.equal(fairOddsRange("-300", "-300").test("0.75"), true);
  assert.equal(fairOddsRange("+300", "+300").test("0.25"), true);
  assert.equal(fairOddsRange("-100", "+100").test("0.5"), true);
  assert.equal(
    fairOddsRange("-300", "-300").test("0.75000000000000000000001"),
    false,
  );
  assert.equal(fairOddsRange("", "+300").test("0.2"), false);
});
test("invalid bounds and missing fair estimates fail closed when filtering", () => {
  for (const pair of [
    ["50", ""],
    ["x", ""],
    ["+300", "-200"],
  ])
    assert.equal(fairOddsRange(...(pair as [string, string])).valid, false);
  for (const p of [null, undefined, "0", "-1", "1.1", "NaN"])
    assert.equal(fairOddsRange("-200", "+300").test(p), false);
  assert.equal(fairOddsRange("", "").test(null), true);
});
