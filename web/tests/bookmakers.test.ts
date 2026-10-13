import { test } from "node:test";
import assert from "node:assert/strict";
import { feedBooks } from "../lib/bookmakers";

test("main filters include the new books without stored quotes", () => {
  const ids = feedBooks([]).map((b) => b.id);
  assert.ok(ids.includes("betopenly"));
  assert.ok(ids.includes("polymarket"));
  assert.ok(ids.includes("pinnacle"));
});
test("props include all configured books and preserve additional captured books", () => {
  const books = feedBooks(
    [
      { id: "another", name: "Another book" },
      { id: "polymarket", name: "Polymarket" },
    ],
    true,
  );
  for (const id of [
    "prizepicks",
    "underdog",
    "polymarket",
    "betopenly",
    "another",
  ])
    assert.ok(books.some((b) => b.id === id));
  assert.equal(books.filter((b) => b.id === "polymarket").length, 1);
});
