import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  PlacedChip,
  PlacedNoteFor,
  PlacedProvider,
} from "../components/placed";
import { betKey, placedIndex, placedState } from "../lib/placed";
import { quoteRef } from "../lib/slip";
import type { TrackerBet } from "../lib/tracker-api";

const quote = {
  game_id: "g1",
  contract_id: "g1:h2h",
  market_key: "h2h",
  side: "home",
  point: null,
};
const propRef = {
  game_id: "e1",
  market_key: "prop",
  prop_market: "player_points",
  player: "Jayson Tatum",
  side: "over",
  point: 24.5,
};
const bet = (over: Partial<TrackerBet>): TrackerBet =>
  ({
    id: "b",
    status: "pending",
    book: "fanduel",
    stake_cents: 2500,
    ref: quoteRef(quote),
    ...over,
  }) as TrackerBet;

test("a tracked bet matches the same selection at the same book, whatever the price", () => {
  const index = placedIndex([bet({})]);
  const hit = placedState(index, [
    { ref: quoteRef(quote), bookLabel: "FanDuel" },
  ]);
  assert.deepEqual(hit, { legs: 1, placed: 1, stakeCents: 2500 });
});

test("a different book, side, line or game is not the same bet", () => {
  const index = placedIndex([bet({})]);
  const miss = (ref: object, bookLabel = "FanDuel") =>
    placedState(index, [{ ref: ref as never, bookLabel }]).placed;
  assert.equal(miss(quoteRef(quote), "DraftKings"), 0);
  assert.equal(miss(quoteRef({ ...quote, side: "away" })), 0);
  assert.equal(miss(quoteRef({ ...quote, contract_id: "g1:totals:220.5" })), 0);
  assert.equal(miss(quoteRef({ ...quote, game_id: "g2" })), 0);
  assert.equal(miss(quoteRef({ ...quote, market_key: "h2h_lay" })), 0);
});

test("only open bets count, and stakes on the same bet add up", () => {
  const index = placedIndex([
    bet({ id: "1" }),
    bet({ id: "2", stake_cents: 1000 }),
    bet({ id: "3", status: "won" }),
    bet({ id: "4", status: "void" }),
  ]);
  assert.deepEqual(
    placedState(index, [{ ref: quoteRef(quote), bookLabel: "FanDuel" }]),
    { legs: 1, placed: 1, stakeCents: 3500 },
  );
  assert.equal(placedIndex([bet({ status: "lost" })]).size, 0);
});

test("player props match on market, player, side and line", () => {
  const index = placedIndex([bet({ ref: propRef, book: "draftkings" })]);
  const at = (ref: object) =>
    placedState(index, [{ ref: ref as never, bookLabel: "DraftKings" }]).placed;
  assert.equal(at(propRef), 1);
  assert.equal(at({ ...propRef, player: " jayson tatum " }), 1);
  assert.equal(at({ ...propRef, point: 25.5 }), 0);
  assert.equal(at({ ...propRef, side: "under" }), 0);
  assert.equal(at({ ...propRef, prop_market: "player_assists" }), 0);
});

test("manual and incomplete bets never match anything", () => {
  assert.equal(betKey(undefined, "fanduel"), null);
  assert.equal(betKey({}, "fanduel"), null);
  assert.equal(betKey({ game_id: "g", side: "home" }, "fanduel"), null);
  assert.equal(placedIndex([bet({ ref: {} })]).size, 0);
});

const render = (slip: TrackerBet[], ref: object, bookLabel: string) =>
  renderToStaticMarkup(
    <PlacedProvider slip={slip}>
      <PlacedChip leg={{ ref: ref as never, bookLabel }} />
      <PlacedNoteFor leg={{ ref: ref as never, bookLabel }} />
    </PlacedProvider>,
  );

test("a placed bet shows a badge with its stake and a warning note", () => {
  const html = render([bet({})], quoteRef(quote), "FanDuel");
  assert.match(html, /placed-badge/);
  assert.match(html, /✓<\/span> Placed</);
  assert.doesNotMatch(html, /\$/);
  assert.match(html, /Already placed/);
});

test("a bet that was not placed shows nothing", () => {
  assert.equal(render([bet({})], quoteRef(quote), "DraftKings"), "");
  assert.equal(render([], quoteRef(quote), "FanDuel"), "");
});
