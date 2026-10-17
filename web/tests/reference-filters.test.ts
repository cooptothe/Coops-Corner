import assert from "node:assert/strict";
import { test } from "node:test";
import { savedWinChance, passesWinChance } from "../lib/reference-filters";

test("winning chance slider validates saved values and exact bounds", () => {
  assert.equal(savedWinChance("150"), "100");
  assert.equal(savedWinChance("bad"), "0");
  assert.equal(passesWinChance(0.6, "60"), true);
  assert.equal(passesWinChance(0.59, "60"), false);
  assert.equal(passesWinChance(NaN, "0"), false);
  assert.equal(passesWinChance(1, "100"), true);
});
