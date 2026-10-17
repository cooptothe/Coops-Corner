import type { TrendReport } from "./trends-api";
export type HistoryWindow = "5" | "10" | "20" | "h2h";
export function labHistory(
  report: TrendReport,
  window: HistoryWindow,
  line: number,
  side: "Over" | "Under",
) {
  const source = [...(report.history_games ?? report.games)].sort(
    (a, b) => Date.parse(b.date) - Date.parse(a.date),
  );
  // The report's matchup sample is descriptive; use the current away/home opponent
  // only when the player's matched team is supplied by the source adapter.
  const currentOpponent = report.opponent;
  const games =
    window === "h2h"
      ? source.filter(
          (game) => !!currentOpponent && game.opponent === currentOpponent,
        )
      : source.slice(0, Number(window));
  const values = games
    .map((game) => Number(game.value))
    .filter(Number.isFinite);
  const wins = values.filter((value) =>
    side === "Over" ? value > line : value < line,
  ).length;
  const pushes = values.filter((value) => value === line).length;
  const decisive = values.length - pushes;
  const ordered = [...values].sort((a, b) => a - b);
  return {
    games,
    wins,
    pushes,
    decisive,
    hitRate: decisive ? wins / decisive : null,
    mean: values.length
      ? values.reduce((a, b) => a + b, 0) / values.length
      : null,
    median: ordered.length
      ? (ordered[Math.floor((ordered.length - 1) / 2)] +
          ordered[Math.floor(ordered.length / 2)]) /
        2
      : null,
  };
}
