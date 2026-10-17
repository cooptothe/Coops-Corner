import { builderLeg, type ParlayLeg } from "./parlay";
import type { TrendContract } from "./trends-api";

export const labHref = (betId?: string) =>
  betId ? `/lab?${new URLSearchParams({ bet: betId })}` : "/lab";

export function labDate(value: string, short = false): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    month: "short",
    day: "numeric",
    ...(!short && {
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }),
  }).format(date);
}

export function labLeg(contract: TrendContract): ParlayLeg | null {
  if (
    !contract.event_id ||
    (["Yes", "No"].includes(contract.side) &&
      (contract.settlement_point !== null || contract.point !== "0.5")) ||
    !contract.point.trim() ||
    !["Over", "Under", "Yes", "No"].includes(contract.side) ||
    !contract.starts_at ||
    !Number.isFinite(Date.parse(contract.starts_at)) ||
    !contract.observed_at ||
    !Number.isFinite(Date.parse(contract.observed_at)) ||
    !Number.isFinite(Number(contract.point)) ||
    Number(contract.price) <= 1 ||
    !Number.isFinite(Number(contract.price))
  )
    return null;
  return builderLeg(
    {
      gameId: contract.event_id ?? "",
      bookId: contract.book,
      matchup: `${contract.away} @ ${contract.home}`,
      line: `${contract.player} · ${contract.side}${["Yes", "No"].includes(contract.side) ? "" : ` ${contract.point}`}`,
      market: contract.market_label ?? contract.market_key,
      sportKey: contract.sport_key,
      startsAt: contract.starts_at,
      decimalOdds: contract.price,
      observedAt: contract.observed_at,
      links: contract.links,
      sourceIds: contract.source_ids,
      ref: {
        game_id: contract.event_id ?? "",
        market_key: "prop",
        prop_market: contract.market_key,
        player: contract.player,
        side: contract.side.toLowerCase(),
        point:
          contract.settlement_point === null ? null : Number(contract.point),
        away: contract.away,
        home: contract.home,
        lab_contract_id: contract.id,
      },
    },
    "prop",
  );
}
