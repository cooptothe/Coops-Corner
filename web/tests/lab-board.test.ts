import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_LAB_FILTERS,
  filterLabBoard,
  labBoardBase,
} from "../lib/lab-board";
import type { TrendContract } from "../lib/trends-api";
const a: TrendContract = {
  id: "a",
  bet_id: "a",
  event_id: "game",
  sport_key: "basketball_nba",
  player: "Player A",
  market_key: "player_points",
  market_label: "Points",
  home: "Home",
  away: "Away",
  starts_at: "2030-01-02T01:00:00Z",
  observed_at: "2030-01-01T15:00:00Z",
  point: "20.5",
  side: "Over",
  price: "2",
  book: "draftkings",
  commission: null,
};
const b = {
  ...a,
  id: "b",
  bet_id: "b",
  player: "Player B",
  side: "Under",
  price: "1.8",
};
test("all available props remain researchable without EV, reference books, known fees or history", () => {
  assert.equal(filterLabBoard([a, b], DEFAULT_LAB_FILTERS, {}).length, 2);
  assert.equal(
    labBoardBase(
      [a, { ...a, id: "best", book: "fanduel", price: "2.2" }],
      DEFAULT_LAB_FILTERS,
    )[0].id,
    "best",
  );
});
test("league, Central date, matchup, side, book, player and prop filters select inventory", () => {
  assert.equal(
    filterLabBoard(
      [a, b],
      {
        ...DEFAULT_LAB_FILTERS,
        date: "2030-01-01",
        side: "Under",
        search: "player b",
        team: "Home",
        market: "player_points",
        game: "game",
      },
      {},
    ).length,
    1,
  );
  assert.equal(
    filterLabBoard([a], { ...DEFAULT_LAB_FILTERS, date: "2030-01-02" }, {})
      .length,
    0,
  );
  assert.equal(
    filterLabBoard([a], { ...DEFAULT_LAB_FILTERS, book: "fanduel" }, {}).length,
    0,
  );
});
test("hit-rate and sample filters use matching loaded history and never invent missing rates", () => {
  const rates = {
    a: {
      id: "a",
      status: "available",
      price: a.price,
      observed_at: a.observed_at,
      windows: {
        "10": {
          games: 10,
          wins: 7,
          losses: 2,
          pushes: 1,
          hit_rate: 7 / 9,
          mean: 23,
          median: 22,
          historical_interval: null,
        },
      },
    },
  };
  assert.equal(
    filterLabBoard(
      [a, b],
      { ...DEFAULT_LAB_FILTERS, minRate: 70, minGames: 8 },
      rates,
    ).length,
    1,
  );
  assert.equal(
    filterLabBoard([a], { ...DEFAULT_LAB_FILTERS, minRate: 80 }, rates).length,
    0,
  );
  assert.equal(
    filterLabBoard(
      [{ ...a, price: "3" }],
      { ...DEFAULT_LAB_FILTERS, minRate: 70 },
      rates,
    ).length,
    0,
  );
});
test("American odds filters validate bounds and default filtering leaves source data unchanged", () => {
  const before = JSON.stringify([a, b]);
  assert.equal(
    filterLabBoard(
      [a, b],
      { ...DEFAULT_LAB_FILTERS, minOdds: "+100", maxOdds: "+200" },
      {},
    ).length,
    1,
  );
  assert.equal(
    filterLabBoard([a, b], { ...DEFAULT_LAB_FILTERS, minOdds: "50" }, {})
      .length,
    0,
  );
  assert.equal(JSON.stringify([a, b]), before);
});
