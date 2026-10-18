import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { LabInsight } from "../components/lab-insight";
import { LabChart } from "../components/lab-chart";
import type { TrendReport } from "../lib/trends-api";
const report: TrendReport = JSON.parse(
  readFileSync("../fixtures/trends/report.json", "utf8"),
);
test("quick read explains results without changing probabilities or calling history an edge", () => {
  const original = JSON.stringify(report);
  const html = renderToStaticMarkup(
    <LabInsight
      report={{
        ...report,
        projection: {
          status: "research_only",
          method: "baseline",
          probability: 0.612,
          projected_mean: 22.5,
          push_probability: 0,
          model_ev: 0.1,
          live_feed_eligible: false,
          edge_validated: false,
        },
      }}
    />,
  );
  for (const label of [
    "What to know",
    "Recent results",
    "Model outlook",
    "Before you bet",
    "61.2%",
    "22.5",
    "not a validated",
    "Chart filters",
  ])
    assert.ok(html.includes(label), label);
  assert.equal(JSON.stringify(report), original);
  assert.doesNotMatch(html, /guaranteed|proven edge/i);
});
test("missing data and a real zero chance are distinguished", () => {
  const missing = renderToStaticMarkup(
    <LabInsight
      report={{ ...report, windows: {}, news_status: "unavailable" }}
    />,
  );
  assert.match(missing, /History unavailable/);
  assert.match(missing, /More data needed/);
  assert.match(missing, /Check injuries/);
  const zero = renderToStaticMarkup(
    <LabInsight
      report={{
        ...report,
        projection: {
          status: "research_only",
          method: "baseline",
          probability: 0,
          live_feed_eligible: false,
          edge_validated: false,
        },
      }}
    />,
  );
  assert.match(zero, /0.0%/);
});
test("player profile uses the shared headshot component with initials fallback", () => {
  const html = renderToStaticMarkup(<LabChart report={report} />);
  assert.match(html, /avatar-player/);
  assert.match(html, /width:56px/);
  assert.ok(html.includes(report.player));
});
