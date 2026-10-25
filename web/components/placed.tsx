"use client";
import { Icon } from "./icon";
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

export const isPlaced = (s: PlacedState) =>
  s.legs > 0 && (s.placed > 0 || !!s.related);

const label = (s: PlacedState) =>
  s.related
    ? s.related.level === "market"
      ? "Same market"
      : `${s.related.kind === "player" ? "Player" : s.related.kind === "team" ? "Team" : "Event"} bet placed`
    : s.parlayLegs === s.legs
      ? "In parlay"
      : s.placed === s.legs
        ? "Placed"
        : `${s.placed}/${s.legs} placed`;

// Shown on a feed row.
export function PlacedBadge({ state }: { state: PlacedState }) {
  if (!isPlaced(state)) return null;
  return (
    <span
      className={`placed-badge ${state.related?.level === "entity" ? "related" : "same-market"} ${state.placed === state.legs ? "all" : "some"}`}
      aria-label={label(state)}
      title={
        state.related?.level === "entity"
          ? `You have an open bet on this ${state.related.kind} in another market for this event.`
          : "You have an open bet on this market. Check your tracker before betting again."
      }
    >
      <Icon name="check" />
      <span className="placed-label-full">{label(state)}</span>
      <span className="placed-label-compact" aria-hidden="true">
        {state.related
          ? "Related"
          : state.parlayLegs === state.legs
            ? "Parlay"
            : state.placed === state.legs
              ? "Placed"
              : `${state.placed}/${state.legs}`}
      </span>
    </span>
  );
}

// Shown in a drawer, above the button that would track it again.
export function PlacedNote({ state }: { state: PlacedState }) {
  if (!isPlaced(state)) return null;
  if (state.related)
    return (
      <div
        role="status"
        className={`placed-note ${state.related.level === "entity" ? "related" : "same-market"}`}
      >
        <strong>
          {state.related.level === "market"
            ? "Bet placed on this market"
            : label(state)}
        </strong>
        <span>
          {state.related.level === "market"
            ? "You have an open bet on this market, possibly at another line, side, or sportsbook."
            : `You have an open bet on this ${state.related.kind} in a different market for this event.`}{" "}
          Review your tracker before adding more exposure.
        </span>
      </div>
    );
  const all = state.placed === state.legs;
  return (
    <div role="status" className="placed-note same-market">
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
