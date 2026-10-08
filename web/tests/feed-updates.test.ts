import assert from "node:assert/strict";
import { test } from "node:test";
import { diffIds } from "../components/feed-updates";

const ids = (...xs: string[]) => new Set(xs);

test("an update reports what it added and what it removed", () => {
  assert.deepEqual(diffIds(ids("a", "b", "c"), ids("b", "c", "d", "e")), {
    added: 2,
    removed: 1,
  });
});

test("identical rows are no change, whatever their order", () => {
  assert.deepEqual(diffIds(ids("a", "b"), ids("b", "a")), {
    added: 0,
    removed: 0,
  });
});

test("an empty update removes everything, an empty start adds everything", () => {
  assert.deepEqual(diffIds(ids("a", "b"), ids()), { added: 0, removed: 2 });
  assert.deepEqual(diffIds(ids(), ids("a", "b")), { added: 2, removed: 0 });
});
