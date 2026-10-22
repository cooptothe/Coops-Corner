import { dayKey } from "./schedule";

export const TIME_FILTERS = [
  ["default", "All available"],
  ["8h", "Next 8 hours"],
  ["today", "Today"],
  ["24h", "Next 24 hours"],
  ["3d", "Next 3 days"],
  ["1w", "Next 7 days"],
] as const;
export type TimeFilter = (typeof TIME_FILTERS)[number][0];

// Rolling windows include their upper boundary and exclude games already started.
export function matchesFeedTime(
  startsAt: string,
  filter: TimeFilter,
  now: number,
  live = false,
): boolean {
  if (filter === "default") return true;
  const start = Date.parse(startsAt);
  if (!Number.isFinite(start) || (live ? start > now : start <= now))
    return false;
  if (filter === "today") return dayKey(start) === dayKey(now);
  const hours = { "8h": 8, "24h": 24, "3d": 72, "1w": 168 }[filter];
  return live
    ? start >= now - hours * 60 * 60 * 1000
    : start <= now + hours * 60 * 60 * 1000;
}

export function savedTimeFilter(value: unknown): TimeFilter {
  return TIME_FILTERS.some(([key]) => key === value)
    ? (value as TimeFilter)
    : "default";
}
