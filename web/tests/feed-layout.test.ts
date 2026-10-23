import { test } from "node:test";
import assert from "node:assert/strict";
import { feedLayout, feedOffsets, feedWindow } from "../lib/feed-layout";
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

test("scrolling reuses the measured height index and matches a rebuilt window", () => {
  const ids = Array.from({ length: 10000 }, (_, i) => `row-${i}`);
  const sizes = new Map([
    ["row-10", 400],
    ["row-100", 180],
  ]);
  const offsets = feedOffsets(ids, sizes, 200);
  for (const scroll of [0, 199, 2000, 20000, 1900000]) {
    const window = feedWindow(offsets, scroll, 650, 6);
    assert.equal(window.offsets, offsets);
    assert.deepEqual(window, feedLayout(ids, sizes, 200, scroll, 650, 6));
  }
});
