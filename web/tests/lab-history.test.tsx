import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { labHistory } from "../lib/lab-history";
import { LabChart } from "../components/lab-chart";
import type { TrendReport } from "../lib/trends-api";
const report: TrendReport = JSON.parse(
  readFileSync("../fixtures/trends/report.json", "utf8"),
);
test("Lab windows use full available history, exclude pushes and match the exact opponent", () => {
  const history = Array.from({ length: 25 }, (_, i) => ({
    ...report.games[0],
    id: String(i),
    date: new Date(Date.UTC(2030, 0, 30 - i, 20)).toISOString(),
    value: String(i % 3 === 0 ? 10 : i % 3 === 1 ? 12 : 8),
    opponent: i % 2 ? "Other" : "Opponent",
  }));
  const input = { ...report, opponent: "Opponent", history_games: history };
  assert.equal(labHistory(input, "20", 10, "Over").games.length, 20);
  const five = labHistory(input, "5", 10, "Over");
  assert.equal(five.wins, 2);
  assert.equal(five.pushes, 2);
  assert.equal(five.hitRate, 2 / 3);
  assert.equal(five.median, 10);
  const h2h = labHistory(input, "h2h", 10, "Under");
  assert.equal(h2h.games.length, 13);
  assert.ok(h2h.games.every((g) => g.opponent === "Opponent"));
  assert.equal(
    labHistory({ ...input, opponent: undefined }, "h2h", 10, "Over").games
      .length,
    0,
  );
  assert.equal(labHistory(input, "5", 30, "Over").hitRate, 0);
});
test("dashboard renders accessible windows, target input, chart and odds comparison", () => {
  const html = renderToStaticMarkup(<LabChart report={report} />);
  for (const label of [
    "L5",
    "L10",
    "L20",
    "H2H",
    "Try a line",
    "HIT RATE",
    "MEDIAN",
    "Compare sportsbook odds",
    "not the line offered",
  ])
    assert.ok(html.includes(label), label);
  assert.match(html, /role="img"/);
  assert.match(html, /No saved sportsbook odds/);
});

test("venue and result splits exclude unknown evidence and recompute decisive hit rates", () => {
  const rows = Array.from({ length: 12 }, (_, i) => ({
    ...report.games[0],
    id: String(i),
    date: new Date(Date.UTC(2030, 0, 31 - i)).toISOString(),
    season: 2030,
    home: i < 10 ? i % 2 === 0 : null,
    game_result: i % 3 === 0 ? ("L" as const) : ("W" as const),
    value: String(i === 0 ? 10 : 12),
    workload: i === 6 ? null : "30",
  }));
  const input = { ...report, history_games: rows };
  const home = labHistory(input, "10", 10, "Over", {
    venue: "home",
    result: "W",
    minWorkload: 25,
  });
  assert.equal(home.games.length, 3);
  assert.ok(
    home.games.every(
      (g) => g.home === true && g.game_result === "W" && g.workload !== null,
    ),
  );
  assert.equal(home.hitRate, 1);
  assert.equal(
    labHistory(
      {
        ...input,
        history_games: rows.map((g) => ({ ...g, game_result: undefined })),
      },
      "10",
      10,
      "Over",
      { result: "W" },
    ).games.length,
    0,
  );
});
test("season view uses available full-season logs while projection history stays bounded", () => {
  const rows = Array.from({ length: 65 }, (_, i) => ({
    ...report.games[0],
    id: String(i),
    date: new Date(Date.UTC(2030, 0, 31 - i)).toISOString(),
    season: 2030,
    value: "12",
  }));
  assert.equal(
    labHistory(
      { ...report, history_games: rows.slice(0, 40), season_games: rows },
      "season",
      10,
      "Over",
    ).games.length,
    65,
  );
  assert.equal(
    labHistory(
      { ...report, history_games: rows.slice(0, 40), season_games: rows },
      "5",
      10,
      "Under",
    ).hitRate,
    0,
  );
});
