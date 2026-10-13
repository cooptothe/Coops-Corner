import { test } from "node:test";
import assert from "node:assert/strict";
import { feedBooks } from "../lib/bookmakers";

test("canonical capitalization wins over raw provider IDs", () => {
  const books = feedBooks(
    ["betopenly", "polymarket", "prizepicks", "underdog"].map((id) => ({
      id,
      name: id,
    })),
    true,
  );
  for (const [id, name] of [
    ["betopenly", "BetOpenly"],
    ["polymarket", "Polymarket"],
    ["prizepicks", "PrizePicks"],
    ["underdog", "Underdog"],
  ])
    assert.equal(books.find((b) => b.id === id)?.name, name);
});

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
