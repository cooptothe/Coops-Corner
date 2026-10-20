import { test } from "node:test";
import assert from "node:assert/strict";
import { feedBooks } from "../lib/bookmakers";

test("canonical capitalization wins over raw provider IDs", () => {
  const books = feedBooks(
    ["betopenly", "polymarket", "williamhill_us", "fanatics"].map((id) => ({
      id,
      name: id,
    })),
    true,
  );
  for (const [id, name] of [
    ["betopenly", "BetOpenly"],
    ["polymarket", "Polymarket"],
    ["williamhill_us", "Caesars"],
    ["fanatics", "Fanatics"],
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
    "williamhill_us",
    "fanatics",
    "polymarket",
    "betopenly",
    "another",
  ])
    assert.ok(books.some((b) => b.id === id));
  assert.equal(books.filter((b) => b.id === "polymarket").length, 1);
});

test("withdrawn DFS sources cannot reappear from retained captures", () => {
  const ids = feedBooks(
    ["prizepicks", "underdog", "pick6", "dabble_us_dfs"].map((id) => ({
      id,
      name: id,
    })),
    true,
  ).map((b) => b.id);
  for (const id of ["prizepicks", "underdog", "pick6", "dabble_us_dfs"])
    assert.ok(!ids.includes(id));
});
