"use client";
import { useEffect, useRef, useState } from "react";

export interface FeedChange {
  added: number;
  removed: number;
}

export function diffIds(
  before: ReadonlySet<string>,
  current: ReadonlySet<string>,
): FeedChange {
  let added = 0;
  let removed = 0;
  for (const id of current) if (!before.has(id)) added += 1;
  for (const id of before) if (!current.has(id)) removed += 1;
  return { added, removed };
}

// Compares each new set of row ids with the last one, so a refresh can say what it replaced.
// Pass the ids of the underlying data, not of the filtered list, and a `scope` that changes
// whenever the settings that decide membership change (those are not data updates).
export function useFeedChanges(
  ids: string[] | null,
  scope = "",
): FeedChange | null {
  const previous = useRef<{ scope: string; ids: Set<string> } | null>(null);
  const [change, setChange] = useState<FeedChange | null>(null);
  useEffect(() => {
    if (!ids) return;
    const current = new Set(ids);
    const before = previous.current;
    previous.current = { scope, ids: current };
    if (!before || before.scope !== scope) {
      setChange(null);
      return;
    }
    const { added, removed } = diffIds(before.ids, current);
    if (added || removed) setChange({ added, removed });
  }, [ids, scope]);
  return change;
}

export function FeedChangeNote({ change }: { change: FeedChange | null }) {
  if (!change) return null;
  return (
    <span
      className="feed-change"
      role="status"
      title="What the latest update added to and removed from this list"
    >
      ↻ {change.added} new · {change.removed} gone
    </span>
  );
}

// Keeps the open bet on screen when an update drops it, so it can be shown as unavailable
// instead of vanishing mid-calculation. `present` says whether the bet is still in the data
// at all (a bet merely hidden by a filter is not "gone").
export function useOpenBet<T extends { id: string }>(
  selected: string | null,
  active: T | null,
  present: boolean,
): { shown: T | null; unavailable: boolean } {
  const [last, setLast] = useState<T | null>(null);
  useEffect(() => {
    if (active) setLast(active);
  }, [active]);
  const gone =
    selected !== null && !active && !present && last?.id === selected;
  return { shown: active ?? (gone ? last : null), unavailable: gone };
}
