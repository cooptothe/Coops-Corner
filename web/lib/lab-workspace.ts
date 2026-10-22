import type { TrendContract } from "./trends-api";
import { labGameId, labQuoteCurrent } from "./lab";

export const propLabel = (c: TrendContract) =>
  c.market_label ??
  c.market_key.replace(/^(player|batter|pitcher)_/, "").replaceAll("_", " ");
export function leagueName(key: string) {
  const names: Record<string, string> = {
    basketball_nba: "NBA",
    basketball_wnba: "WNBA",
    americanfootball_nfl: "NFL",
    baseball_mlb: "MLB",
    icehockey_nhl: "NHL",
    soccer_epl: "EPL",
    soccer_usa_mls: "MLS",
  };
  return names[key] ?? key.split("_").slice(1).join(" ").toUpperCase();
}

/** One player/market per game. Pick the most widely quoted actual line;
 * never average different alt lines into a fictional sportsbook offer.
 * One vote per book per line prevents opposite sides inflating coverage.
 */
export function labPlayerRows(contracts: TrendContract[]): TrendContract[] {
  const groups = new Map<string, TrendContract[]>();
  for (const c of contracts) {
    const key = JSON.stringify([labGameId(c), c.player, c.market_key]);
    const group = groups.get(key) ?? [];
    group.push(c);
    groups.set(key, group);
  }
  return [...groups.values()].map((all) => {
    const fresh = all.filter((c) => labQuoteCurrent(c));
    const latest = new Map<string, number>();
    for (const c of all)
      latest.set(
        c.book,
        Math.max(latest.get(c.book) ?? 0, Date.parse(c.observed_at ?? "") || 0),
      );
    const group = fresh.length
      ? fresh
      : all.filter(
          (c) =>
            (Date.parse(c.observed_at ?? "") || 0) ===
            (latest.get(c.book) ?? 0),
        );
    const lines = new Map<string, Set<string>>();
    for (const c of group) {
      const books = lines.get(c.point) ?? new Set<string>();
      books.add(c.book);
      lines.set(c.point, books);
    }
    const sorted = [...lines].sort(
      (a, b) => b[1].size - a[1].size || Number(a[0]) - Number(b[0]),
    );
    const line = sorted[0][0];
    return group
      .filter((c) => c.point === line)
      .sort(
        (a, b) =>
          Number(["Over", "Yes"].includes(b.side)) -
            Number(["Over", "Yes"].includes(a.side)) ||
          Number(b.price) - Number(a.price) ||
          a.id.localeCompare(b.id),
      )[0];
  });
}

export function virtualRows(count: number, scrollTop: number, height = 528) {
  const start = Math.min(
    Math.max(0, count - 1),
    Math.max(0, Math.floor(scrollTop / 44) - 5),
  );
  const end = Math.min(count, Math.ceil((scrollTop + height) / 44) + 5);
  return {
    start,
    end,
    top: start * 44,
    bottom: Math.max(0, (count - end) * 44),
  };
}
