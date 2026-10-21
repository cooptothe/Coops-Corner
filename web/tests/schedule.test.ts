import assert from "node:assert/strict";
import { test } from "node:test";
import type { Quote } from "../lib/contracts";
import { buildGameLines, dayHeading, dayKey, timeLabel } from "../lib/schedule";

let n = 0;
function q(
  book: string,
  market: string,
  contract: string,
  side: string,
  decimal: number,
  point: number | null = null,
  game = "g1",
): Quote {
  return {
    id: `q${++n}`,
    game_id: game,
    contract_id: contract,
    market_key: market,
    sportsbook_id: book,
    selection_id: side,
    selection_name: side,
    side,
    point: point == null ? null : String(point),
    decimal_odds: String(decimal),
    commission_rate: "0",
    observed_at: "2030-01-01T00:00:00Z",
  } as Quote;
}
const pair = (
  book: string,
  contract: string,
  home: number,
  away: number,
  homePoint: number,
) => [
  q(book, "spreads", contract, "home", home, homePoint),
  q(book, "spreads", contract, "away", away, -homePoint),
];
const all = () => true;

test("main line is the one most books quote; best price comes from that line", () => {
  const quotes = [
    ...pair("fanduel", "s:-3.5", 1.91, 1.91, -3.5),
    ...pair("draftkings", "s:-3.5", 1.95, 1.87, -3.5),
    ...pair("betmgm", "s:-3.5", 1.89, 1.93, -3.5),
    // One book posts an alternate line with a juicier price: it must not win.
    ...pair("novig", "s:-2.5", 2.4, 1.6, -2.5),
  ];
  const line = buildGameLines(quotes, all).get("g1")!.spreads!;
  assert.equal(line.books, 3);
  assert.equal(line.sides.home.bookId, "draftkings");
  assert.equal(line.sides.home.decimal, 1.95);
  assert.equal(line.sides.home.point, -3.5);
  assert.equal(line.sides.away.bookId, "betmgm");
  assert.equal(line.sides.away.point, 3.5);
});

test("a tie in book count goes to the line nearest even money", () => {
  const quotes = [
    ...pair("fanduel", "s:-7", 1.5, 2.6, -7),
    ...pair("fanduel", "s:-3", 1.9, 1.92, -3),
  ];
  const line = buildGameLines(quotes, all).get("g1")!.spreads!;
  assert.equal(line.sides.home.point, -3);
});

test("only allowed books count, and sharps can be excluded", () => {
  const quotes = [
    ...pair("pinnacle", "s:-3.5", 2.1, 1.8, -3.5),
    ...pair("fanduel", "s:-3.5", 1.91, 1.91, -3.5),
  ];
  const line = buildGameLines(quotes, (b) => b !== "pinnacle").get(
    "g1",
  )!.spreads!;
  assert.equal(line.sides.home.bookId, "fanduel");
  assert.equal(line.books, 1);
});

test("totals and a three-way moneyline", () => {
  const quotes = [
    q("fanduel", "totals", "t:48.5", "over", 1.9, 48.5),
    q("fanduel", "totals", "t:48.5", "under", 1.9, 48.5),
    q("betmgm", "totals", "t:48.5", "over", 1.95, 48.5),
    q("betmgm", "totals", "t:48.5", "under", 1.85, 48.5),
    q("fanduel", "h2h", "h", "home", 2.5),
    q("fanduel", "h2h", "h", "away", 2.9),
    q("fanduel", "h2h", "h", "draw", 3.3),
    q("betmgm", "h2h", "h", "draw", 3.4),
    q("betmgm", "h2h", "h", "home", 2.45),
    q("betmgm", "h2h", "h", "away", 3.0),
  ];
  const lines = buildGameLines(quotes, all).get("g1")!;
  assert.equal(lines.totals!.sides.over.bookId, "betmgm");
  assert.equal(lines.totals!.sides.under.bookId, "fanduel");
  assert.equal(lines.h2h!.sides.draw.decimal, 3.4);
  assert.equal(lines.h2h!.sides.away.decimal, 3.0);
  assert.equal(lines.h2h!.sides.home.decimal, 2.5);
});

test("one-sided or lay markets produce nothing, and games stay separate", () => {
  const quotes = [
    q("fanduel", "spreads", "s", "home", 1.9, -3.5),
    q("fanduel", "h2h_lay", "h", "home", 2, null),
    q("fanduel", "h2h", "h2", "home", 2, null, "g2"),
    q("fanduel", "h2h", "h2", "away", 1.8, null, "g2"),
  ];
  const lines = buildGameLines(quotes, all);
  assert.equal(lines.get("g1"), undefined);
  assert.ok(lines.get("g2")!.h2h);
});

test("a tied best price is stable and prefers the first book", () => {
  const quotes = [
    ...pair("fanduel", "s", 1.91, 1.91, -3.5),
    ...pair("betmgm", "s", 1.91, 1.91, -3.5),
  ];
  const first = buildGameLines(quotes, all).get("g1")!.spreads!;
  const second = buildGameLines([...quotes].reverse(), all).get("g1")!.spreads!;
  assert.equal(first.sides.home.bookId, "betmgm");
  assert.equal(second.sides.home.bookId, "betmgm");
});

test("days follow the Chicago calendar, with Today and Tomorrow labels", () => {
  // 03:30Z on Oct 9 is 10:30 PM on Oct 8 in Chicago.
  assert.equal(dayKey("2026-10-09T03:30:00Z"), "2026-10-08");
  assert.equal(dayKey("2026-10-09T06:00:00Z"), "2026-10-09");
  const now = Date.parse("2026-10-08T15:00:00Z");
  assert.equal(dayHeading("2026-10-08", now), "Today · Thursday, October 8");
  assert.equal(dayHeading("2026-10-09", now), "Tomorrow · Friday, October 9");
  assert.equal(dayHeading("2026-10-11", now), "Sunday, October 11");
  assert.equal(timeLabel("2026-10-09T00:15:00Z"), "7:15 PM");
});

test("expanded cash books can supply schedule best prices", () => {
  for (const book of ["betonlineag", "williamhill_us", "bovada"]) {
    const quotes = [
      ...pair("draftkings", "s:-3.5", 1.9, 1.9, -3.5),
      ...pair(book, "s:-3.5", 2.1, 2.1, -3.5),
    ];
    const line = buildGameLines(quotes, all).get("g1")!.spreads!;
    assert.equal(line.sides.home.bookId, book);
    assert.equal(line.sides.away.bookId, book);
  }
});
