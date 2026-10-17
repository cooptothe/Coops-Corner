import type { TrendReport } from "./trends-api";
export type HistoryWindow = "5" | "10" | "20" | "h2h" | "season";
export interface HistorySplits {
  venue?: "all" | "home" | "away";
  result?: "all" | "W" | "L";
  h2h?: boolean;
  minWorkload?: number;
}
export function labHistory(
  report: TrendReport,
  window: HistoryWindow,
  line: number,
  side: "Over" | "Under",
  splits: HistorySplits = {},
) {
  const source = [
    ...(window === "season"
      ? (report.season_games ?? report.history_games ?? report.games)
      : (report.history_games ?? report.games)),
  ]
    .filter(
      (g) =>
        g.value.trim() !== "" &&
        Number.isFinite(Number(g.value)) &&
        Number.isFinite(Date.parse(g.date)),
    )
    .sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  const season = Math.max(...source.map((g) => g.season));
  const eligible = source.filter(
    (g) =>
      (splits.venue !== "home" || g.home === true) &&
      (splits.venue !== "away" || g.home === false) &&
      (!splits.result ||
        splits.result === "all" ||
        g.game_result === splits.result) &&
      (!(splits.h2h || window === "h2h") ||
        (!!report.opponent && g.opponent === report.opponent)) &&
      (!(splits.minWorkload && splits.minWorkload > 0) ||
        (g.workload != null &&
          Number.isFinite(Number(g.workload)) &&
          Number(g.workload) >= splits.minWorkload)) &&
      (window !== "season" || g.season === season),
  );
  const games = ["h2h", "season"].includes(window)
    ? eligible
    : eligible.slice(0, Number(window));
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
