import { labBoardBase, DEFAULT_LAB_FILTERS } from "../lib/lab-board";
import assert from "node:assert/strict";
import { test } from "node:test";
import { labPlayerRows, virtualRows, leagueName } from "../lib/lab-workspace";
import type { TrendContract } from "../lib/trends-api";
const quote = (
  id: string,
  book: string,
  point: string,
  side = "Over",
  price = "1.91",
): TrendContract => ({
  id,
  bet_id: id,
  event_id: "game",
  sport_key: "basketball_nba",
  player: "Player",
  market_key: "player_points",
  home: "Home",
  away: "Away",
  side,
  point,
  price,
  book,
});
test("player rail uses widely quoted real line, never synthetic median or repeated sides", () => {
  const rows = labPlayerRows([
    quote("a", "a", "20.5"),
    quote("b", "a", "20.5", "Under"),
    quote("c", "b", "21.5"),
    quote("d", "c", "21.5"),
    quote("e", "d", "21.5", "Over", "2.1"),
  ]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].point, "21.5");
  assert.equal(rows[0].id, "e");
});
test("players, markets and games stay separate; one-sided Yes props stay researchable", () => {
  const a = quote("a", "a", "0.5", "Yes");
  assert.equal(
    labPlayerRows([
      a,
      { ...a, id: "b", player: "Other" },
      { ...a, id: "c", event_id: "other" },
      { ...a, id: "d", market_key: "player_rebounds" },
    ]).length,
    4,
  );
  assert.equal(labPlayerRows([a])[0].side, "Yes");
  assert.equal(leagueName("icehockey_nhl"), "NHL");
});
test("ten thousand props mount only a bounded virtual viewport, including after filters shrink", () => {
  const range = virtualRows(10000, 44000);
  assert.ok(range.end - range.start <= 23);
  assert.equal(range.top, range.start * 44);
  const empty = virtualRows(0, 99999);
  assert.equal(empty.start, 0);
  assert.equal(empty.end, 0);
  const narrowed = virtualRows(2, 99999);
  assert.ok(narrowed.start < narrowed.end);
  assert.equal(narrowed.end, 2);
});

test("board preserves book votes before selecting the primary line", () => {
  const offers = [
    quote("a", "a", "20.5"),
    quote("b", "b", "21.5"),
    quote("c", "c", "21.5"),
    quote("d", "d", "21.5"),
  ];
  const rows = labPlayerRows(labBoardBase(offers, DEFAULT_LAB_FILTERS, true));
  assert.equal(rows[0].point, "21.5");
});

test("new current lines replace stale research defaults", () => {
  const stale = {
    ...quote("old", "a", "20.5"),
    quote_status: "stale" as const,
    observed_at: "2026-01-01T00:00:00Z",
  };
  const fresh = {
    ...quote("new", "b", "22.5"),
    quote_status: "current" as const,
  };
  assert.equal(
    labPlayerRows([stale, { ...stale, id: "old2", book: "c" }, fresh])[0].id,
    "new",
  );
  const saved = {
    ...quote("saved", "a", "23.5"),
    quote_status: "stale" as const,
    observed_at: "2026-01-02T00:00:00Z",
  };
  assert.equal(labPlayerRows([stale, saved])[0].id, "saved");
});
