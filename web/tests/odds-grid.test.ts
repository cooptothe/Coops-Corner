import assert from "node:assert/strict";
import test from "node:test";
import type { Quote } from "../lib/contracts";
import { bestQuoteId, buildBoard, movement, sidesFor } from "../lib/odds-grid";

const q = (
  id: string,
  book: string,
  side: string,
  point: string | null,
  odds: string,
  contract = "c1",
  market = "spreads",
) =>
  ({
    id,
    game_id: "g1",
    contract_id: contract,
    market_key: market,
    sportsbook_id: book,
    selection_id: side,
    selection_name: side,
    side,
    point,
    decimal_odds: odds,
    commission_rate: "0",
    observed_at: "2026-01-01T00:00:00Z",
  }) as unknown as Quote;

test("board keeps the line nearest even money per book", () => {
  const board = buildBoard(
    [
      q("a", "dk", "home", "-3.5", "1.91", "c1"),
      q("b", "dk", "away", "3.5", "1.91", "c1"),
      q("c", "dk", "home", "-7.5", "2.4", "c2"),
      q("d", "dk", "away", "7.5", "1.55", "c2"),
    ],
    "spreads",
  );
  assert.equal(board.get("g1")?.get("dk")?.home?.point, -3.5);
});

test("best price prefers the better line, then the better odds", () => {
  const p = (quoteId: string, decimal: number, point: number | null) => ({
    quoteId,
    decimal,
    point,
  });
  assert.equal(
    bestQuoteId("spreads", "home", [p("x", 1.95, -3.5), p("y", 1.8, -2.5)]),
    "y",
  );
  assert.equal(
    bestQuoteId("totals", "over", [p("x", 1.9, 48.5), p("y", 1.9, 47.5)]),
    "y",
  );
  assert.equal(
    bestQuoteId("h2h", "home", [p("x", 1.9, null), p("y", 2.1, null)]),
    "y",
  );
  assert.equal(
    bestQuoteId("h2h", "home", [p("x", 1.9, null), p("y", 1.9, null)]),
    null,
  );
});

test("movement and sides", () => {
  const a = { quoteId: "a", decimal: 1.9, point: null };
  assert.equal(movement("h2h", "home", a, { ...a, decimal: 2 }), "up");
  assert.equal(movement("h2h", "home", a, { ...a, decimal: 1.8 }), "down");
  assert.equal(movement("h2h", "home", a, a), null);
  assert.deepEqual(sidesFor("h2h", true), ["away", "draw", "home"]);
  assert.deepEqual(sidesFor("totals", false), ["over", "under"]);
});
