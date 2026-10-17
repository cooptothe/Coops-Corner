import assert from "node:assert/strict";
import { test } from "node:test";
import { netBackOdds } from "../lib/pricing";

test("straight returns include commission without binary-float tracking artifacts", () => {
  assert.equal(netBackOdds("1.95", "0.02"), "1.931000000000");
  assert.equal(netBackOdds("2", "0.02"), "1.980000000000");
  assert.equal(netBackOdds("2", "0"), "2.000000000000");
});
test("unknown and invalid commissions cannot become free straight bets", () => {
  for (const fee of [null, "-0.01", "1"])
    assert.throws(() => netBackOdds("2", fee));
});
