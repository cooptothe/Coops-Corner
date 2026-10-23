import { test } from "node:test";
import assert from "node:assert/strict";
import { feedLayout } from "../lib/feed-layout";
test("measured cards preserve every pixel and visible ranges as long text grows", () => {
  const ids = ["a", "b", "c", "d"];
  const sizes = new Map([
    ["a", 100],
    ["b", 380],
    ["c", 150],
  ]);
  const result = feedLayout(ids, sizes, 200, 120, 300, 0);
  assert.deepEqual(result.offsets, [0, 100, 480, 630, 830]);
  assert.equal(result.total, 830);
  assert.equal(result.first, 1);
  assert.equal(result.last, 2);
  assert.equal(feedLayout([], sizes, 200, 0, 300).total, 0);
  assert.equal(feedLayout(["a"], sizes, 200, 900, 300).last, 1);
});
