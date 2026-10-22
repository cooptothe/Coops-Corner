"use client";
import { useSyncExternalStore } from "react";
import { quoteClock } from "./quote-age";
export function Countdown({ value }: { value: string }) {
  const now = useSyncExternalStore(
    quoteClock.subscribe,
    quoteClock.getSnapshot,
    () => 0,
  );
  if (!now) return null;
  const ms = new Date(value).getTime() - now;
  if (!value || Number.isNaN(ms)) return null;
  if (ms <= 0) return <span>started</span>;
  const m = Math.floor(ms / 60000);
  const d = Math.floor(m / 1440);
  return (
    <span>
      starts in{" "}
      {d > 0
        ? `${d}d ${Math.floor((m % 1440) / 60)}h`
        : `${Math.floor(m / 60)}h ${m % 60}m`}
    </span>
  );
}
