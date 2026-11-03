import { test } from "node:test";
import assert from "node:assert/strict";
import { compareDecimal, fixed, percent, mulDecimal, american } from "../../frontend/format.mjs";
test("live near-zero edges and exponent-form prices render with exact decimal arithmetic", () => {
  assert.equal(compareDecimal("1E-8", "0"), 1);
  assert.equal(mulDecimal("1E-8", "100"), "0.000001");
  assert.equal(fixed("-2.5e-7", 8), "-0.00000025");
  assert.equal(percent("1E-8"), percent("0.00000001"));
  assert.equal(american("2.1e0"), american("2.1"));
  assert.equal(compareDecimal("3e2", "300"), 0);
});
test("decimal rendering still rejects malformed or unbounded values", () => {
  for (const value of ["NaN", "Infinity", "1e999", "1e999999", "1e", "0x10", "1/2"])
    assert.throws(() => fixed(value, 2));
});
