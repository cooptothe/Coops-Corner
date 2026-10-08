import assert from "node:assert/strict";
import { test } from "node:test";
import {
  convert,
  efficiencyTier,
  marketWidthCents,
  parseAmerican,
  toAmerican,
  toDecimal,
} from "../lib/promo-math";

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

test("capital counts the cash bet only for a risk-free bet", () => {
  const bonus = convert("bonus", 100, 4.0, 1.303)!;
  assert.equal(bonus.capital, bonus.hedge);
  const free = convert("nosweat", 100, 3.5, 1.364, 0.75)!;
  assert.equal(free.capital, 100 + free.hedge);
});

test("market width is the margin between opposing prices in cents", () => {
  assert.equal(marketWidthCents(toDecimal(200), toDecimal(-220)), 20);
  assert.equal(marketWidthCents(toDecimal(-110), toDecimal(-110)), 20);
  assert.equal(marketWidthCents(toDecimal(350), toDecimal(-450)), 100);
  assert.equal(marketWidthCents(toDecimal(110), toDecimal(105)), 0);
  assert.ok(Math.abs(toAmerican(toDecimal(-110)) + 110) < 1e-9);
});

test("efficiency tiers", () => {
  assert.equal(efficiencyTier(0.6499), "low");
  assert.equal(efficiencyTier(0.65), "mid");
  assert.equal(efficiencyTier(0.7499), "mid");
  assert.equal(efficiencyTier(0.77), "good");
  assert.equal(efficiencyTier(0.8), "elite");
});

test("voucher value is the refund at the assumed rate, risk-free only", () => {
  const free = convert("nosweat", 200, 3.5, 1.364, 0.6)!;
  assert.ok(Math.abs(free.voucherValue - 120) < 1e-9);
  // Cash on the loss path before the voucher is converted.
  assert.ok(
    Math.abs(
      free.ifHedgeWins - free.voucherValue - (-200 + free.hedge * 0.364),
    ) < 1e-9,
  );
  assert.equal(convert("bonus", 100, 4, 1.3)!.voucherValue, 0);
});

test("profit boost: 50% on +200 hedged at -250 locks in about $14.29", () => {
  const c = convert("boost", 100, 3, 1.4, 0.75, { percent: 0.5 })!;
  assert.equal(c.boostedDecimal, 4);
  assert.equal(c.hedge, 285.71);
  assert.ok(Math.abs(c.ifPromoWins - 14.29) < 0.01);
  assert.ok(Math.abs(c.ifHedgeWins - 14.29) < 0.01);
  assert.equal(c.capital, 385.71);
  assert.ok(Math.abs(c.rate - 14.29 / 385.71) < 1e-4);
  assert.equal(c.overMaxStake, false);
  assert.equal(c.capHit, false);
});

test("profit boost applies only to the stake up to the max, and to capped extra winnings", () => {
  const over = convert("boost", 100, 3, 1.4, 0.75, {
    percent: 0.5,
    maxStake: 20,
  })!;
  assert.ok(Math.abs(over.extraWinnings - 20) < 1e-9); // 20 * 2 * 0.5
  assert.equal(over.overMaxStake, true);
  const capped = convert("boost", 100, 3, 1.4, 0.75, {
    percent: 0.5,
    maxExtra: 50,
  })!;
  assert.equal(capped.extraWinnings, 50);
  assert.equal(capped.capHit, true);
  assert.ok(
    capped.profit <
      convert("boost", 100, 3, 1.4, 0.75, { percent: 0.5 })!.profit,
  );
});

test("a 0% boost is a plain arbitrage and efficiency grades on its own scale", () => {
  assert.ok(convert("boost", 100, 3, 1.4, 0.75, { percent: 0 })!.profit < 0);
  assert.equal(efficiencyTier(0.019, "boost"), "low");
  assert.equal(efficiencyTier(0.02, "boost"), "mid");
  assert.equal(efficiencyTier(0.05, "boost"), "good");
  assert.equal(efficiencyTier(0.08, "boost"), "elite");
  assert.equal(efficiencyTier(0.05), "low");
});
