import assert from "node:assert/strict";
import { test } from "node:test";
import { convert, parseAmerican, toDecimal } from "../lib/promo-math";

test("bonus bet hedges to equal cash either way", () => {
  const c = convert("bonus", 100, 4.0, 1.303)!;
  assert.equal(c.hedge, 230.24);
  assert.ok(Math.abs(c.ifPromoWins - 69.76) < 0.01);
  assert.ok(Math.abs(c.ifHedgeWins - 69.76) < 0.01);
  assert.ok(Math.abs(c.rate - 0.6976) < 0.001);
});

test("site credit converts near face value", () => {
  const c = convert("credit", 100, 2.05, 1.952)!;
  assert.equal(c.hedge, 105.02);
  assert.ok(c.rate > 0.99 && c.rate < 1.01);
});

test("no-sweat equalizes the win and the voucher-adjusted loss", () => {
  const c = convert("nosweat", 100, 3.5, 1.364, 0.75)!;
  assert.ok(Math.abs(c.ifPromoWins - c.ifHedgeWins) < 0.01);
  assert.ok(c.profit > 0);
});

test("rejects bad inputs and parses American odds", () => {
  assert.equal(convert("bonus", 0, 4, 2), null);
  assert.equal(convert("bonus", 100, 1, 2), null);
  assert.equal(parseAmerican("+300"), 300);
  assert.equal(parseAmerican("-110"), -110);
  assert.equal(parseAmerican("50"), null);
  assert.equal(toDecimal(300), 4);
});
