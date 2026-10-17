import assert from "node:assert/strict";
import { test } from "node:test";
import { passesPropEdge } from "../lib/prop-edge";
test("props require strictly positive EV and respect the inclusive user threshold", () => {
  assert.equal(passesPropEdge("0", "0"), false);
  assert.equal(passesPropEdge("-0.01", "0"), false);
  assert.equal(passesPropEdge("0.000001", "0"), true);
  assert.equal(passesPropEdge("0.02", "0.02"), true);
  assert.equal(passesPropEdge("0.019999", "0.02"), false);
});
