import { labHistory } from "./lab-history";
import { labDay, labGameId } from "./lab";
import type { TrendContract, TrendSummary, TrendReport } from "./trends-api";
export type LabWindow = "5" | "10" | "20" | "season" | "h2h";
export interface LabRates {
  id: string;
  status: string;
  warm_attempted?: boolean;
  recent_values?: string[];
  price?: string;
  observed_at?: string | null;
  windows?: Record<string, TrendSummary>;
}
export interface LabFilters {
  sport: string;
  date: string;
  game: string;
  team: string;
  market: string;
  side: string;
  book: string;
  search: string;
  minOdds: string;
  maxOdds: string;
  minRate: number;
  minGames: number;
  window: LabWindow;
  sort: string;
}
export const DEFAULT_LAB_FILTERS: LabFilters = {
  sport: "",
  date: "",
  game: "",
  team: "",
  market: "",
  side: "",
  book: "",
  search: "",
  minOdds: "",
  maxOdds: "",
  minRate: 0,
  minGames: 0,
  window: "10",
  sort: "time",
};
export const validLabOdds = (text: string) =>
  text.trim() === "" ||
  (/^[+-]?\d+$/.test(text.trim()) && Math.abs(Number(text)) >= 100);
export function currentRates(
  contract: TrendContract,
  rates?: LabRates,
): LabRates | undefined {
  return rates?.price === contract.price &&
    rates.observed_at === contract.observed_at
    ? rates
    : undefined;
}
export function labBoardBase(
  contracts: TrendContract[],
  filters: LabFilters,
  retainBooks = false,
): TrendContract[] {
  const query = filters.search.trim().toLowerCase();
  const selected = contracts.filter(
    (c) =>
      (!filters.sport || c.sport_key === filters.sport) &&
      (!filters.date || labDay(c.starts_at) === filters.date) &&
      (!filters.game || labGameId(c) === filters.game) &&
      (!filters.team || [c.home, c.away].includes(filters.team)) &&
      (!filters.market || c.market_key === filters.market) &&
      (!filters.side || c.side === filters.side) &&
      (!filters.book || c.book === filters.book) &&
      (!query ||
        `${c.player} ${c.market_label ?? c.market_key} ${c.home} ${c.away}`
          .toLowerCase()
          .includes(query)),
  );
  if (retainBooks) return selected;
  const choices = new Map<string, TrendContract>();
  for (const c of selected) {
    const key = JSON.stringify([
      labGameId(c),
      c.player,
      c.market_key,
      c.point,
      c.side,
      c.price_kind === "indicative" ? c.book : "cash",
    ]);
    const prior = choices.get(key);
    if (
      !prior ||
      Number(c.price) > Number(prior.price) ||
      (Number(c.price) === Number(prior.price) && c.id < prior.id)
    )
      choices.set(key, c);
  }
  return [...choices.values()];
}
export function filterLabBoard(
  contracts: TrendContract[],
  filters: LabFilters,
  rates: Record<string, LabRates>,
  retainBooks = false,
): TrendContract[] {
  if (!validLabOdds(filters.minOdds) || !validLabOdds(filters.maxOdds))
    return [];
  const american = (price: string) => {
    const n = Number(price);
    return n >= 2 ? (n - 1) * 100 : -100 / (n - 1);
  };
  const rows = labBoardBase(contracts, filters, retainBooks).filter((c) => {
    const rate = currentRates(c, rates[c.id])?.windows?.[filters.window];
    const odds = american(c.price);
    if (c.price_kind === "indicative" && (filters.minOdds || filters.maxOdds))
      return false;
    return (
      (!filters.minOdds || odds >= Number(filters.minOdds)) &&
      (!filters.maxOdds || odds <= Number(filters.maxOdds)) &&
      (!filters.minRate ||
        (rate?.hit_rate != null && rate.hit_rate * 100 >= filters.minRate)) &&
      (!filters.minGames || (rate != null && rate.games >= filters.minGames))
    );
  });
  return rows.sort((a, b) => {
    if (filters.sort === "name")
      return a.player.localeCompare(b.player) || a.id.localeCompare(b.id);
    if (filters.sort === "rate") {
      const x =
        currentRates(a, rates[a.id])?.windows?.[filters.window]?.hit_rate ?? -1;
      const y =
        currentRates(b, rates[b.id])?.windows?.[filters.window]?.hit_rate ?? -1;
      if (x !== y) return y - x;
    }
    return (
      Date.parse(a.starts_at ?? "") - Date.parse(b.starts_at ?? "") ||
      a.player.localeCompare(b.player) ||
      a.id.localeCompare(b.id)
    );
  });
}

export function reportRates(report: TrendReport): LabRates {
  const season = labHistory(
    report,
    "season",
    Number(report.contract.point),
    ["Under", "No"].includes(report.contract.side) ? "Under" : "Over",
  );
  return {
    id: report.contract.id,
    status: "available",
    recent_values: [...(report.history_games ?? report.games)]
      .sort((a, b) => Date.parse(b.date) - Date.parse(a.date))
      .slice(0, 5)
      .reverse()
      .map((g) => g.value),
    price: report.contract.price,
    observed_at: report.contract.observed_at,
    windows: {
      ...report.windows,
      h2h: report.matchup,
      season: {
        games: season.games.length,
        wins: season.wins,
        losses: season.decisive - season.wins,
        pushes: season.pushes,
        hit_rate: season.hitRate,
        mean: season.mean,
        median: season.median,
        historical_interval: null,
      },
    },
  };
}
