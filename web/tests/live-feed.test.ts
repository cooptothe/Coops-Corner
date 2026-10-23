import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_LIVE_FEED,
  gameState,
  matchesLiveState,
  liveRows,
  liveProduct,
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

test("live product keeps standard feed contracts and expires rows without inventing new timestamps", () => {
  const row = {
    id: "live:one",
    kind: "positive_ev",
    game_id: "open",
    quote_ids: ["q"],
    market_key: "h2h",
  } as import("../lib/contracts").ToolRow;
  const enriched: LiveFeed = {
    ...feed,
    events: [
      {
        ...feed.events[0],
        commence_time: "2026-10-22T17:00:00Z",
        tool_rows: [row],
        quotes: [],
        opportunities: [
          {
            ...candidate,
            row_id: row.id,
            expires_at: Date.parse(feed.as_of) / 1000 + 5,
          },
        ],
      },
    ],
  };
  const product = liveProduct(enriched, "active", 4000);
  assert.equal(product.rows.length, 1);
  assert.equal(product.rows[0], row);
  assert.equal(product.data.games[0].starts_at, "2026-10-22T17:00:00Z");
  assert.equal(product.data.games[0].competition, "NBA");
  assert.equal(product.data.caps.books.length, 16);
  assert.equal(liveProduct(enriched, "active", 5000).rows.length, 0);
  assert.equal(liveProduct(enriched, "no_active_lines", 0).rows.length, 0);
});

test("Pause requires fresh reported game stoppage, not absent sportsbook lines", () => {
  const now = 1000;
  const playing = {
    ...feed.events[1],
    game_status: "in_play" as const,
    game_status_source: "espn" as const,
    game_status_expires_at: 1020,
  };
  const paused = {
    ...feed.events[0],
    game_status: "paused" as const,
    game_status_source: "espn" as const,
    game_status_expires_at: 1020,
  };
  assert.equal(matchesLiveState(playing, "paused", now), false);
  assert.equal(matchesLiveState(playing, "playing", now), true);
  assert.equal(matchesLiveState(paused, "paused", now), true);
  assert.equal(matchesLiveState(paused, "playing", now), false);
  assert.equal(matchesLiveState(paused, "paused", 1021), false);
  assert.equal(gameState(feed.events[1], now), "unknown");
});

test("an empty live shell provides feed controls with no manufactured games or bets", () => {
  const product = liveProduct(EMPTY_LIVE_FEED, "", 0);
  assert.deepEqual(product.rows, []);
  assert.deepEqual(product.data.games, []);
  assert.deepEqual(product.data.quotes, []);
  assert.ok(product.data.caps.books.length);
  assert.ok(product.data.caps.tools.includes("positive_ev"));
});
