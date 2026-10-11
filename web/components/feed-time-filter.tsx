"use client";
import { useCallback, useEffect, useState } from "react";
import {
  matchesFeedTime,
  TIME_FILTERS,
  type TimeFilter,
} from "../lib/feed-time";

export function useFeedTimeFilter() {
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
    (startsAt: string) => matchesFeedTime(startsAt, timeFilter, now),
    [timeFilter, now],
  );
  return { timeFilter, setTimeFilter: choose, matchesTime };
}

export function FeedTimeFilter({
  value,
  onChange,
}: {
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
              ? "Upcoming games today in America/Chicago"
              : key === "default"
                ? "Show all available event times"
                : undefined
          }
        >
          {label}
        </button>
      ))}
    </div>
  );
}
