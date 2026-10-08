import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { LineChart } from "../components/tracker-chart";
import { BetRow, KpiRibbon } from "../components/tracker-parts";
import type { LiveView, TrackerBet } from "../lib/tracker-api";
import { kpis } from "../lib/tracker-math";

const bet = (over: Partial<TrackerBet> = {}): TrackerBet => ({
  id: "b1",
  client_key: "k",
  group_id: null,
  created_at: "2026-03-01T12:00:00+00:00",
  placed_at: "2026-03-01T12:00:00+00:00",
  strategy: "prop",
  sport_key: "basketball_nba",
  matchup: "Boston Celtics at Miami Heat",
  starts_at: "2026-03-01T23:30:00+00:00",
  market: "Rebounds",
  selection: "Jayson Tatum Over 5.5 REB",
  book: "fanduel",
  odds: "2.1",
  stake_cents: 5000,
  stake_type: "cash",
  status: "pending",
  returned_cents: null,
  settled_at: null,
  fair_prob: null,
  ev_ratio: null,
  ref: { player: "Jayson Tatum", side: "over", point: 5.5 },
  clv: null,
  notes: "",
  ...over,
});
const noop = () => undefined;
const row = (b: TrackerBet, live?: LiveView) =>
  renderToStaticMarkup(
    <table>
      <tbody>
        <BetRow
          bet={b}
          live={live}
          selected={false}
          onSelect={noop}
          onApply={noop}
        />
      </tbody>
    </table>,
  );

test("an open prop shows its live progress, the game clock and the book", () => {
  const html = row(bet(), {
    state: "in",
    detail: "4:12 - 3rd Quarter",
    score: { away: 60, home: 58 },
    progress: { value: 3, line: 5.5, side: "over" },
    suggest: null,
  });
  assert.match(html, /Jayson Tatum Over 5\.5 REB/);
  assert.match(html, /4:12 - 3rd Quarter/);
  assert.match(html, /3 \/ 5\.5/);
  assert.match(html, /role="progressbar"/);
  assert.match(html, />FD</);
  assert.match(html, /\+110/);
  assert.match(html, /to win \$55\.00/);
});

test("a cleared over reads as cleared and a finished game offers a suggestion", () => {
  const html = row(bet(), {
    state: "post",
    detail: "Final",
    score: {},
    progress: { value: 8, line: 5.5, side: "over" },
    suggest: { result: "won", basis: "Box score: 8 vs 5.5" },
  });
  assert.match(html, /trk-bar cleared/);
  assert.match(html, /looks like WON/);
});

test("a settled bet shows profit and result, and a bonus bet says so", () => {
  const won = row(
    bet({
      status: "won",
      returned_cents: 10500,
      settled_at: "2026-03-02T01:00:00+00:00",
    }),
  );
  assert.match(won, /\+\$55\.00/);
  assert.match(won, /trk-res won/);
  const free = row(bet({ stake_type: "bonus" }));
  assert.match(free, /BONUS BET/);
});

test("the ribbon shows empty states without inventing numbers", () => {
  const html = renderToStaticMarkup(
    <KpiRibbon kpi={kpis([])} bankroll={0} pendingTotal={0} />,
  );
  assert.match(html, /\$0\.00/);
  assert.match(html, /No closing lines measured yet/);
  assert.match(html, /Settle bets to draw a trend/);
  const graded = kpis([
    bet({
      status: "won",
      returned_cents: 10500,
      settled_at: "2026-03-02T01:00:00+00:00",
    }),
    bet({
      id: "b2",
      status: "lost",
      returned_cents: 0,
      settled_at: "2026-03-03T01:00:00+00:00",
    }),
  ]);
  const filled = renderToStaticMarkup(
    <KpiRibbon kpi={graded} bankroll={105000} pendingTotal={2500} />,
  );
  assert.match(filled, /\+\$5\.00/);
  assert.match(filled, /1-1-0 W-L-P/);
  assert.match(filled, /\$1,050\.00/);
});

test("the chart draws a line per series and explains an empty history", () => {
  const html = renderToStaticMarkup(
    <LineChart
      label="Bankroll"
      days={["2026-03-01", "2026-03-02", "2026-03-03"]}
      series={[
        {
          label: "Bankroll",
          color: "#10b981",
          values: [100000, 105000, 98000],
        },
      ]}
    />,
  );
  assert.match(html, /<path/);
  assert.match(html, /role="img"/);
  assert.match(html, /2026-03-03/);
  assert.match(
    renderToStaticMarkup(<LineChart label="x" days={[]} series={[]} />),
    /Not enough history/,
  );
});
