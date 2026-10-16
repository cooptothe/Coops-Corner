import test from "node:test";
import assert from "node:assert/strict";
import { marketWidth, widestMarket, matchesEvLimits } from "../lib/ev-filters";

test("market width uses American cents continuously across even money", () => {
  assert.equal(marketWidth(["2", "2"]), 0);
  assert.equal(marketWidth([String(1 + 100 / 110), String(1 + 100 / 110)]), 20);
  assert.equal(marketWidth(["2.2", String(1 + 100 / 140)]), 20);
  assert.equal(
    widestMarket([
      ["2", "2"],
      ["2.2", String(1 + 100 / 140)],
    ]),
    20,
  );
});

test("missing, one-sided and three-way references have unknown width", () => {
  for (const prices of [[], ["2"], ["2", "3", "4"], ["NaN", "2"], ["1", "2"]]) {
    assert.equal(marketWidth(prices), null);
  }
  assert.equal(widestMarket([["2", "2"], ["2"]]), null);
});

test("maximum EV is inclusive, exact, and independent of the width limit", () => {
  assert.equal(matchesEvLimits("0.05", 20, "5", "20"), true);
  assert.equal(matchesEvLimits("0.050000001", 20, "5", "20"), false);
  assert.equal(matchesEvLimits("0.02", 21, "5", "20"), false);
  assert.equal(matchesEvLimits("0", 0, "0", "0"), true);
  assert.equal(matchesEvLimits("0.05", null, "5", ""), true);
  assert.equal(matchesEvLimits("0.05", null, "5", "20"), false);
  assert.equal(matchesEvLimits("0.05", 20, "bad", ""), false);
  assert.equal(matchesEvLimits("0.05", 20, "", "-1"), false);
});
