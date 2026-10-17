import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { TrendResults } from "../components/props-trends";
import type { TrendReport } from "../lib/trends-api";

const report: TrendReport = JSON.parse(
  readFileSync("../fixtures/trends/report.json", "utf8"),
);

test("Trends presents the requested windows, evidence, push counts and honest model labels", () => {
  const html = renderToStaticMarkup(<TrendResults report={report} />);
  for (const label of [
    "Last 1",
    "Last 5",
    "Last 10",
    "Baseline",
    "pushes",
    "Previous games vs",
    "Same home/away",
    "Game-by-game evidence",
    "Player &amp; matchup news",
    "Historical model check",
  ])
    assert.ok(html.includes(label), label);
  assert.match(html, /not calibrated/);
  assert.match(html, /not the line offered/);
  assert.match(html, /does not confirm/);
  assert.match(html, /Check the latest injury report/);
  assert.match(html, /<svg/);
  assert.doesNotMatch(html, /guaranteed|proven edge/i);
});

test("missing estimates remain unavailable and unavailable news is explicit", () => {
  const html = renderToStaticMarkup(
    <TrendResults
      report={{
        ...report,
        model_probability: null,
        model_ev: null,
        research_signal: false,
        news_status: "unavailable",
      }}
    />,
  );
  assert.match(html, /Unavailable/);
  assert.match(html, /News is temporarily unavailable/);
  assert.doesNotMatch(html, /Research candidate/);
});

test("source text is escaped rather than treated as markup", () => {
  const html = renderToStaticMarkup(
    <TrendResults report={{ ...report, player: "<script>evil()</script>" }} />,
  );
  assert.ok(!html.includes("<script>"));
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /noopener noreferrer/);
});

test("projection baselines display their research status and never promise an edge", () => {
  const html = renderToStaticMarkup(
    <TrendResults
      report={{
        ...report,
        projection: {
          status: "research_only",
          method: "count_distribution",
          projected_mean: 12,
          probability: 0.6,
          push_probability: 0.1,
          model_ev: 0.2,
          live_feed_eligible: false,
          edge_validated: false,
          models: [
            {
              method: "smoothed_empirical",
              win: 0.55,
              push: 0.1,
              loss: 0.35,
              ev: 0.2,
            },
          ],
          assumptions: ["Unchanged role distribution."],
        },
      }}
    />,
  );
  assert.match(html, /Statistical projection/);
  assert.match(html, /not a validated/);
  assert.match(html, /Compare model assumptions/);
  assert.match(html, /refund chance/);
});
