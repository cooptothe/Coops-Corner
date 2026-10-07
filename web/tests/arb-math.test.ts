import { test } from "node:test";
import assert from "node:assert/strict";
import {
  biasedStakes,
  profitPercent,
  symmetricStakes,
} from "../lib/arb-math.ts";

test("symmetric stakes equalize the return on both outcomes", () => {
  const r = symmetricStakes(100, [2.1, 2.05])!;
  assert.deepEqual(r.stakes, [49.4, 50.6]);
  assert.equal(r.stakes[0] + r.stakes[1], 100);
  assert.ok(Math.abs(r.returns[0] - r.returns[1]) < 1);
  assert.ok(r.netProfit > 0);
  assert.ok(Math.abs(profitPercent([2.1, 2.05]) - 0.0373) < 0.001);
});

test("biased stakes break even on the other leg", () => {
  const r = biasedStakes(100, [2.1, 2.05], 0)!;
  assert.equal(r.stakes[1], 48.78);
  assert.equal(r.returns[1], 100);
  assert.equal(r.guaranteedReturn, 100);
  assert.ok(r.bestProfit > 0);
});

test("bad input yields no sizing", () => {
  assert.equal(symmetricStakes(0, [2, 2]), null);
  assert.equal(symmetricStakes(100, [2]), null);
  assert.equal(biasedStakes(100, [1.5, 1.5], 0), null);
});
