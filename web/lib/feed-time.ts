import { dayKey } from "./schedule";

export const TIME_FILTERS = [
  ["default", "Default"],
  ["8h", "Upcoming (Next 8 Hours)"],
  ["today", "Today Only"],
  ["24h", "Next 24 hours"],
  ["3d", "Within 3 days"],
  ["1w", "1 week"],
] as const;
export type TimeFilter = (typeof TIME_FILTERS)[number][0];

// Rolling windows include their upper boundary and exclude games already started.
export function matchesFeedTime(
  startsAt: string,
  filter: TimeFilter,
  now: number,
): boolean {
  if (filter === "default") return true;
  const start = Date.parse(startsAt);
  if (!Number.isFinite(start) || start <= now) return false;
  if (filter === "today") return dayKey(start) === dayKey(now);
  const hours = { "8h": 8, "24h": 24, "3d": 72, "1w": 168 }[filter];
  return start <= now + hours * 60 * 60 * 1000;
}
