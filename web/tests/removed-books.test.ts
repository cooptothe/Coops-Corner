import test from "node:test";
import assert from "node:assert/strict";
import { feedBooks, MAIN_BOOKS, PROP_BOOKS } from "../lib/bookmakers";

test("withdrawn sportsbook stays absent even in a retained catalog", () => {
  for (const books of [
    MAIN_BOOKS,
    PROP_BOOKS,
    feedBooks([{ id: "betonlineag", name: "BetOnline" }]),
  ]) {
    assert.ok(!books.some((book) => book.id === "betonlineag"));
  }
});
