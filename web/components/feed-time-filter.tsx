"use client";
import { useCallback, useEffect, useState } from "react";
import {
  matchesFeedTime,
  TIME_FILTERS,
  type TimeFilter,
} from "../lib/feed-time";

export function useFeedTimeFilter(live = false) {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("default");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const timer = setInterval(tick, 15_000);
    window.addEventListener("focus", tick);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", tick);
    };
  }, []);
  const choose = (value: TimeFilter) => {
    setNow(Date.now());
    setTimeFilter(value);
  };
  const matchesTime = useCallback(
    // Live has no time controls; saved pregame windows must not hide live rows.
    (startsAt: string) => live || matchesFeedTime(startsAt, timeFilter, now),
    [timeFilter, now, live],
  );
  return { timeFilter, setTimeFilter: choose, matchesTime };
}

export function FeedTimeFilter({
  value,
  onChange,
  live = false,
}: {
  live?: boolean;
  value: TimeFilter;
  onChange: (value: TimeFilter) => void;
}) {
  return (
    <div
      className="feed-time-filter"
      role="group"
      aria-label="Event time filter"
    >
      {TIME_FILTERS.map(([key, label]) => (
        <button
          type="button"
          key={key}
          aria-pressed={value === key}
          onClick={() => onChange(key)}
          title={
            key === "today"
              ? live
                ? "Games started today in America/Chicago"
                : "Upcoming games today in America/Chicago"
              : key === "default"
                ? "Show all available event times"
                : undefined
          }
        >
          {live
            ? label
                .replace("Next ", "Started in last ")
                .replace("All available", "All live games")
            : label}
        </button>
      ))}
    </div>
  );
}
