"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";

import {
  NOT_PLACED,
  placedIndex,
  placedState,
  type PlacedIndex,
  type PlacedLeg,
  type PlacedState,
} from "../lib/placed";
import type { TrackerBet } from "../lib/tracker-api";

const PlacedContext = createContext<PlacedIndex | null>(null);

// Each feed wraps itself in this with the account's open bets. Rows and drawers read it through usePlaced, so the
// memoized virtual rows refresh when a bet is tracked without any new props.
export function PlacedProvider({
  slip,
  children,
}: {
  slip: TrackerBet[];
  children: ReactNode;
}) {
  const index = useMemo(() => placedIndex(slip), [slip]);
  return (
    <PlacedContext.Provider value={index}>{children}</PlacedContext.Provider>
  );
}

export function usePlaced(legs: PlacedLeg[]): PlacedState {
  const index = useContext(PlacedContext);
  return index ? placedState(index, legs) : NOT_PLACED;
}

export const isPlaced = (s: PlacedState) => s.legs > 0 && s.placed > 0;

const label = (s: PlacedState) =>
  s.parlayLegs === s.legs
    ? "Placed in parlay"
    : s.placed === s.legs
      ? "Placed"
      : `${s.placed} of ${s.legs} placed`;

// Shown on a feed row.
export function PlacedBadge({ state }: { state: PlacedState }) {
  if (!isPlaced(state)) return null;
  return (
    <span
      className={`placed-badge ${state.placed === state.legs ? "all" : "some"}`}
      title="You already tracked this bet. Check your tracker before betting again."
    >
      <span aria-hidden="true">✓</span> {label(state)}
    </span>
  );
}

// Shown in a drawer, above the button that would track it again.
export function PlacedNote({ state }: { state: PlacedState }) {
  if (!isPlaced(state)) return null;
  const all = state.placed === state.legs;
  return (
    <div role="status" className="placed-note">
      <strong>
        {all
          ? state.legs === 1
            ? "Already placed"
            : "Every leg is already placed"
          : `${state.placed} of ${state.legs} legs already placed`}
      </strong>
      <span>
        You tracked {all ? "this bet" : "part of this play"}. Betting it again
        doubles your exposure.
      </span>
    </div>
  );
}

export function PlacedChip({ leg }: { leg: PlacedLeg }) {
  return <PlacedBadge state={usePlaced([leg])} />;
}

export function PlacedNoteFor({ leg }: { leg: PlacedLeg }) {
  return <PlacedNote state={usePlaced([leg])} />;
}
