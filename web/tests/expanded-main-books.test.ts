import assert from "node:assert/strict";
import test from "node:test";
import { MAIN_BOOKS, PROP_BOOKS, feedBooks } from "../lib/bookmakers";
import { bookCode, bookLabel } from "../lib/tracker-math";

test("new main books are selectable and props references retain their billing tiers", () => {
  for (const id of ["betonlineag", "williamhill_us", "bovada"]) {
    assert.ok(MAIN_BOOKS.some((b) => b.id === id));
    assert.ok(feedBooks([]).some((b) => b.id === id));
  }
  assert.equal(MAIN_BOOKS.length, 15);
  assert.equal(PROP_BOOKS.length, 16);
  assert.ok(PROP_BOOKS.some((b) => b.id === "williamhill_us"));
  assert.ok(
    ["betonlineag", "bovada"].every((id) =>
      PROP_BOOKS.some((b) => b.id === id),
    ),
  );
  assert.equal(bookCode("BetOnline"), "betonlineag");
  assert.equal(bookLabel("bovada"), "Bovada");
});
