import { test } from "node:test";
import assert from "node:assert/strict";
import {
  liveRows,
  liveRange,
  liveFresh,
  liveAmerican,
  type LiveFeed,
} from "../lib/live-feed.ts";
const candidate = {
  expires_at: 1792692100,
  kind: "ev" as const,
  market: "h2h" as const,
  book: "draftkings",
  selection: "Home",
  ev_percent: "2",
};
const feed: LiveFeed = {
  format: "corner.live_odds/1",
  as_of: "2026-10-22T18:00:00Z",
  enabled: true,
  state: "ready",
  monthly_subcap: 500000,
  events: [
    {
      id: "open",
      sport_key: "basketball_nba",
      home_team: "Home",
      away_team: "Away",
      status: "active",
      is_suspended: false,
      active_market_count: 1,
      books: [],
      opportunities: [candidate],
    },
    {
      id: "paused",
      sport_key: "icehockey_nhl",
      home_team: "Home2",
      away_team: "Away2",
      status: "no_active_lines",
      is_suspended: true,
      active_market_count: 0,
      books: [],
      opportunities: [],
    },
  ],
};
test("live play/pause filters keep unavailable games without manufacturing bets", () => {
  assert.equal(liveRows(feed, "ev", "h2h", "", "active").length, 1);
  const stopped = liveRows(feed, "ev", "h2h", "", "no_active_lines");
  assert.equal(stopped.length, 1);
  assert.equal(stopped[0].candidate, null);
  assert.equal(
    liveRows(feed, "ev", "h2h", "basketball_nba", "no_active_lines").length,
    0,
  );
});
test("live source expiry uses server time and stops stale browser results", () => {
  const start = Date.parse(feed.as_of) / 1000;
  assert.equal(
    liveFresh({ ...candidate, expires_at: start + 5 }, feed.as_of, 4000),
    true,
  );
  assert.equal(
    liveFresh({ ...candidate, expires_at: start + 5 }, feed.as_of, 5000),
    false,
  );
  assert.equal(
    liveFresh({ ...candidate, expires_at: start + 90 }, feed.as_of, 20001),
    false,
  );
});
test("live grid windows thousands of rows and clamps after a feed shrinks", () => {
  const range = liveRange(112000, 5000);
  assert.ok(range.end - range.start <= 14);
  assert.equal(range.top, range.start * 112);
  const shrunk = liveRange(112000, 1);
  assert.equal(shrunk.start, 0);
  assert.equal(shrunk.end, 1);
});
test("live price cells consistently display American odds", () => {
  assert.equal(liveAmerican(2.2), "+120");
  assert.equal(liveAmerican(1.5), "-200");
  assert.equal(liveAmerican(1), "—");
});
