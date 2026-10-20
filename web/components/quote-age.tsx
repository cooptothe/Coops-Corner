"use client";
import { memo, useSyncExternalStore } from "react";
import { quoteAgeStatus } from "../lib/quote-age";
import { ageLabel } from "../../frontend/format.mjs";

const listeners = new Set<() => void>();
let clock = 0;
let timer: ReturnType<typeof setInterval> | undefined;
function tick() {
  clock = Date.now();
  listeners.forEach((notify) => notify());
}
function visibility() {
  if (timer) clearInterval(timer);
  timer = undefined;
  if (!document.hidden) {
    tick();
    timer = setInterval(tick, 15000);
  }
}
function subscribe(notify: () => void) {
  listeners.add(notify);
  if (listeners.size === 1) {
    document.addEventListener("visibilitychange", visibility);
    visibility();
  }
  return () => {
    listeners.delete(notify);
    if (!listeners.size) {
      if (timer) clearInterval(timer);
      timer = undefined;
      document.removeEventListener("visibilitychange", visibility);
    }
  };
}
export const QuoteAge = memo(function QuoteAge({
  value,
}: {
  value: string | null;
}) {
  const now = useSyncExternalStore(
    subscribe,
    () => clock,
    () => 0,
  );
  const status = quoteAgeStatus(value, now);
  const review = status === "review" || status === "expired";
  return (
    <span
      className={`ev-age${review ? " ev-age-review" : ""}`}
      title={
        review
          ? "Stored price: confirm current odds at the sportsbook."
          : undefined
      }
    >
      {value && now && status !== "unknown" ? ageLabel(value, now) : "\u2014"}
      {review && (
        <span className="ev-age-warning">
          {status === "expired" ? "Expired price" : "Verify odds"}
        </span>
      )}
    </span>
  );
});
export const quoteClock = { subscribe, getSnapshot: () => clock };
