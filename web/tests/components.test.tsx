import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { Cards, OddsMatrix, Payoffs } from "../components/market-views";
import type { Book, Game, Quote, ToolRow } from "../lib/contracts";
const books: Book[] = [
  { id: "a", name: "Book A", commission: "0" },
  { id: "b", name: "Book B", commission: "0" },
];
const games: Game[] = [
  {
    id: "game",
    name: "Home vs Away",
    competition: "NBA",
    sport_key: "basketball_nba",
    starts_at: "2030-01-01T20:00:00Z",
    scope: "full_game",
    market_keys: ["h2h"],
    quote_count: 2,
    phase: "unknown",
  },
];
const base: Quote = {
  id: "q1",
  game_id: "game",
  contract_id: "contract",
  market_key: "h2h",
  sportsbook_id: "a",
  selection_id: "home",
  selection_name: "Home",
  side: "home",
  point: null,
  decimal_odds: "2.12",
  commission_rate: "0",
  observed_at: "2030-01-01T19:00:00Z",
};
const quotes = new Map([
  ["q1", base],
  [
    "q2",
    {
      ...base,
      id: "q2",
      sportsbook_id: "b",
      selection_id: "away",
      selection_name: "Away",
      decimal_odds: "1.95",
    },
  ],
]);
const row: ToolRow = {
  id: "row",
  game_id: "game",
  contract_id: "contract",
  market_key: "h2h",
  quote_ids: ["q1", "q2"],
  capital_required: "200",
  minimum_profit: "0",
  conditional_ev_ratio: null,
  oldest_observed_at: base.observed_at,
  kind: "arbitrage",
  calculation: {
    legs: [
      { quote_id: "q1", stake: "99.53", profit_if_selection_wins: "10.99" },
      { quote_id: "q2", stake: "100.47", profit_if_selection_wins: "11.02" },
    ],
    minimum_decisive_profit: "10.99",
    minimum_modeled_profit: "0",
    refund_profit: "0",
  },
};
test("React cards distinguish decisive profit from refund-inclusive minimum", () => {
  const html = renderToStaticMarkup(
    <Cards
      rows={[row]}
      books={books}
      games={games}
      quotes={quotes}
      onDetail={() => {}}
    />,
  );
  assert.match(html, /\+5\.50%/);
  assert.match(html, /\$10\.99 if a side wins/);
  assert.match(html, /Modeled minimum \$0\.00/);
  assert.match(html, /\$99\.53/);
  assert.match(html, /\+112/);
  assert.match(html, /-105/);
});
test("React tool table scales stakes and profit to the entered stake", () => {
  const html = renderToStaticMarkup(
    <Cards
      rows={[row]}
      books={books}
      games={games}
      quotes={quotes}
      onDetail={() => {}}
      stake="1000"
    />,
  );
  assert.match(html, /\$497\.65/);
  assert.match(html, /\$54\.95 if a side wins/);
  assert.match(html, /\+5\.50%/);
});
test("React middle displays real downside and window, never fabricated EV", () => {
  const middle: ToolRow = {
    ...row,
    kind: "middle",
    minimum_profit: "-5",
    calculation: {
      legs: [
        { quote_id: "q1", stake: "100" },
        { quote_id: "q2", stake: "100" },
      ],
      coordinate: "home_minus_away",
      double_win_ranges: [[4, 6]],
      payoff: {
        maximum_modeled_profit: "207",
        states: [{ state_id: "score:4:6", net_profit: "207" }],
      },
    },
  };
  const html = renderToStaticMarkup(
    <Cards
      rows={[middle]}
      books={books}
      games={games}
      quotes={quotes}
      onDetail={() => {}}
    />,
  );
  assert.match(html, /\$207\.00/);
  assert.match(html, /-\$5\.00/);
  assert.match(html, /4–6/);
  assert.match(html, /Middle EV is not estimated/);
  assert.doesNotMatch(html, /CONDITIONAL EV/);
});
test("React quote grid keeps exact contracts separate and escapes API names", () => {
  const html = renderToStaticMarkup(
    <OddsMatrix
      quotes={[
        base,
        {
          ...base,
          id: "q3",
          selection_name: "<script>bad</script>",
          contract_id: "other",
          sportsbook_id: "b",
          decimal_odds: "2.5",
        },
      ]}
      books={books}
      onPromo={() => {}}
    />,
  );
  assert.equal((html.match(/scope="row"/g) ?? []).length, 2);
  assert.match(html, /\+150/);
  assert.match(html, /aria-label="No quote"/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});
test("React payoff view keeps negative cash and token face separate", () => {
  const html = renderToStaticMarkup(
    <Payoffs
      rows={[
        ["Loss", "-1.234", "100"],
        ["Win", "25.005", "0"],
      ]}
    />,
  );
  assert.match(html, /-\$1\.23/);
  assert.match(html, /\$25\.01/);
  assert.match(html, /Token face \$100\.00/);
  assert.match(html, /Noncash face/);
});

test("React +EV row names the sharp books and suggests a quarter-Kelly stake", () => {
  const ev: ToolRow = {
    ...row,
    kind: "positive_ev",
    quote_ids: ["q1"],
    capital_required: "100",
    minimum_profit: null,
    conditional_ev_ratio: "0.04",
    calculation: {
      format: "corner.featured_ev/1",
      target_quote_id: "q1",
      stake: "100",
      capital_at_risk: "100",
      conditional_expected_profit: "4",
      conditional_fair_probability: "0.4906",
      conditional_ev_ratio_on_capital: "0.04",
      reference_books: [
        { sportsbook_id: "b", probabilities: [], quote_ids: ["q2"] },
      ],
    },
  };
  const html = renderToStaticMarkup(
    <Cards
      rows={[ev]}
      books={books}
      games={games}
      quotes={quotes}
      onDetail={() => {}}
      bankroll="1000"
    />,
  );
  assert.match(html, /\+4\.00%/);
  assert.match(html, /no-vig from Book B/);
  assert.match(html, /Suggested \$8\.93/);
});
