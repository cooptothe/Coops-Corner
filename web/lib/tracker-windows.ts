import type { TrackerBet } from "./tracker-api";

/** Stable numeric IDs retain existing saved seven/thirty-day preferences. */
export const PERFORMANCE_WINDOWS = [
  { value: 1, label: "Today" },
  { value: -1, label: "Yesterday" },
  { value: 3, label: "Last 3 days" },
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 180, label: "Last 6 months" },
  { value: 0, label: "All time" },
] as const;

export function performanceBounds(
  value: number | null,
  now: number,
): [number | null, number | null] {
  if (value == null || value === 0) return [null, null];
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  if (value === -1) {
    const end = start.getTime();
    start.setDate(start.getDate() - 1);
    return [start.getTime(), end];
  }
  if (value === 180) {
    // Six calendar months, clamped at month end (not a fixed 180 days).
    start.setTime(now);
    const day = start.getDate();
    start.setDate(1);
    start.setMonth(start.getMonth() - 6);
    const last = new Date(
      start.getFullYear(),
      start.getMonth() + 1,
      0,
    ).getDate();
    start.setDate(Math.min(day, last));
  } else if (value === 1 || value === 3) {
    // Today and the previous two local calendar days, including DST changes.
    start.setDate(start.getDate() - (value - 1));
  } else {
    return [now - value * 86400000, now + 1];
  }
  return [start.getTime(), now + 1];
}

/** Ledger dates follow the event shown on the row, with placement as fallback.
 * Today's upcoming games belong to today even before their start time.
 */
export function matchesPerformanceWindow(
  bet: Pick<TrackerBet, "starts_at" | "placed_at">,
  value: number | null,
  now: number,
): boolean {
  if (value == null || value === 0) return true;
  const [start, yesterdayEnd] = performanceBounds(value, now);
  const tomorrow = new Date(now);
  tomorrow.setHours(0, 0, 0, 0);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const end = value === -1 ? yesterdayEnd! : tomorrow.getTime();
  const at = new Date(bet.starts_at ?? bet.placed_at).getTime();
  return Number.isFinite(at) && at >= start! && at < end;
}
